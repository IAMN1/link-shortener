"""
Counting one link's clicks from many requests at once, against PostgreSQL.

``increment_clicks`` moves the counter with a single ``UPDATE ... SET clicks
= clicks + 1``, and the whole reason it does not go through the domain rule
is that the domain rule cannot: reading the entity, calling
``Link.increment_clicks`` and saving it back is three statements, and two
overlapping requests both read the same number, both write it back plus one,
and one click is gone.

Nothing was watching that. Rewriting the method as read-modify-write --
exactly the tidy-up that "one rule in one place" argues for -- left the
whole suite green; measured here, eight threads of fifteen clicks each lost
between 88 and 96 of 120 over four runs.

They run against the throwaway PostgreSQL stack because that is what the
application runs on, not because SQLite is too well behaved to lose an
update: a *file*-backed SQLite loses them too, and rather harder -- 15
clicks of 120 survived, with no errors raised. The in-memory database the
rest of the suite uses cannot host this test for an unrelated reason.
SQLAlchemy gives ``:memory:`` a SingletonThreadPool, so each thread opens a
database of its own and every statement here fails with "no such table".

Two limits, stated rather than discovered later:

* **One process.** An implementation that reads and writes back under an
  in-process lock passes everything here and still loses clicks across
  gunicorn workers -- measured, four processes of thirty clicks kept 42 of
  120. What these tests can prove is that the statement does not lose an
  update between threads; that it does not lose one between processes rests
  on it being a single ``UPDATE``, which the reading of the code shows and
  no test here can.
* **READ COMMITTED.** The application sets no isolation level, so this is
  what PostgreSQL gives it and what these tests assume. Under SERIALIZABLE
  the correct implementation raises ``SerializationFailure`` instead of
  losing anything, and the failure below would read as lost clicks rather
  than as a changed setting.
"""

import threading
import uuid
from datetime import datetime, timezone

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.application.use_cases.links.update_link_stats import (
    UpdateLinkStatsUseCase,
)
from link_shortener.domain import Link, OriginalUrl, ShortCode, UrlHash
from link_shortener.infrastructure.database.repositories.sqlalchemy_link_repository import (
    SQLAlchemyLinkRepository,
)
from link_shortener.infrastructure.logging.handlers.logger.null_logger import (
    NullLogger,
)


WORKERS = 8
CLICKS_EACH = 15


def _make_link():
    """Build a link with a unique hash and code."""
    token = uuid.uuid4().hex
    return Link(
        id=str(uuid.uuid4()),
        url_hash=UrlHash(token + token[:32]),
        short_code=ShortCode(f"c{token[:8]}"),
        original_url=OriginalUrl(f"https://example.com/{token}"),
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture()
def stored_link(app, pg_session_factory):
    """One link, committed and waiting to be clicked.

    ``app`` is requested for its schema: it is the fixture that creates the
    tables on the PostgreSQL stack.
    """
    link = _make_link()
    session = pg_session_factory()
    SQLAlchemyLinkRepository(session).save(link)
    session.commit()
    session.close()
    return link


def _click_concurrently(session_factory, short_code):
    """
    Fire ``WORKERS`` threads of ``CLICKS_EACH`` clicks at one link.

    Args:
        session_factory: Callable returning a fresh session.
        short_code: The link every thread clicks.

    Returns:
        List of failures, empty when every click committed.
    """
    failures = []
    barrier = threading.Barrier(WORKERS)

    def worker():
        barrier.wait()
        for _ in range(CLICKS_EACH):
            session = session_factory()
            try:
                SQLAlchemyLinkRepository(session).increment_clicks(short_code)
                session.commit()
            except Exception as error:  # noqa: BLE001 - recorded, not handled
                session.rollback()
                failures.append(f"{type(error).__name__}: {error}")
            finally:
                session.close()

    threads = [threading.Thread(target=worker) for _ in range(WORKERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return failures


class TestNoClickIsLost:
    """Every committed click has to show up in the counter."""

    def test_every_simultaneous_click_is_counted(
        self, pg_session_factory, stored_link
    ):
        """
        A hundred and twenty clicks land as a hundred and twenty.

        The number is asserted against the literal the threads were told to
        produce, not against a count read back from the same rows: a
        read-modify-write implementation loses clicks silently, and a test
        that compares the counter to itself would agree with any number it
        found.
        """
        failures = _click_concurrently(
            pg_session_factory, stored_link.short_code
        )
        assert not failures, failures

        session = pg_session_factory()
        try:
            link = SQLAlchemyLinkRepository(session).find_by_code(
                stored_link.short_code
            )
        finally:
            session.close()

        # The contention, not the product. WORKERS = 1 with CLICKS_EACH =
        # 120 keeps the arithmetic and removes the race, and a wholly
        # unatomic implementation passes it.
        assert WORKERS > 1
        assert link.clicks == WORKERS * CLICKS_EACH == 120

    def test_the_counter_moves_by_one_per_call_under_no_contention(
        self, pg_session_factory, stored_link
    ):
        """
        The same statement, alone, so a failure above means contention.

        Without this a broken UPDATE and a lost race look the same in the
        report, and the first thing anyone would suspect is the threads.
        """
        session = pg_session_factory()
        try:
            repository = SQLAlchemyLinkRepository(session)
            first = repository.increment_clicks(stored_link.short_code)
            session.commit()
            second = repository.increment_clicks(stored_link.short_code)
            session.commit()
        finally:
            session.close()

        assert (first.clicks, second.clicks) == (1, 2)


class TestTheUseCaseTheRedirectRunsIsAtomicToo:
    """
    The layer production calls, not the one underneath it.

    ``UpdateLinkStatsUseCase`` is what the redirect schedules; the
    repository is how it does the work today. Pinning atomicity one layer
    down leaves the use case free to be rewritten as read, apply the domain
    rule, save -- which is what the tidy-up would touch first, and which
    kept the whole suite green while losing 92 clicks of 120.
    """

    def test_every_simultaneous_click_through_the_use_case_is_counted(
        self, app, pg_session_factory, stored_link
    ):
        """
        The same hundred and twenty, driven where the redirect drives them.

        Args:
            app: Supplies the container the use case is built from.
            pg_session_factory: Sessions for the final read.
            stored_link: The link every thread clicks.
        """
        with app.app_context():
            use_case = UpdateLinkStatsUseCase(
                uow_factory=app.container.get_uow_factory(),
                logger=NullLogger(),
            )

        failures = []
        barrier = threading.Barrier(WORKERS)
        code = stored_link.short_code.value

        def worker():
            barrier.wait()
            for _ in range(CLICKS_EACH):
                try:
                    use_case.execute(code, RequestContext(request_id="clicks"))
                except Exception as error:  # noqa: BLE001 - recorded
                    failures.append(f"{type(error).__name__}: {error}")

        threads = [threading.Thread(target=worker) for _ in range(WORKERS)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not failures, failures

        session = pg_session_factory()
        try:
            link = SQLAlchemyLinkRepository(session).find_by_code(
                stored_link.short_code
            )
        finally:
            session.close()

        assert WORKERS > 1
        assert link.clicks == WORKERS * CLICKS_EACH == 120
