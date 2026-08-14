"""
Tests for the ``clean-expired`` maintenance path.

The command is named after expiry and works by it. Sweeping by
``last_accessed`` instead removes permanent links their owners have simply
not clicked lately, and leaves the expired ones -- the rows that make a
URL unshortenable -- exactly where they were.
"""

from datetime import datetime, timedelta, timezone

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.domain import Link, OriginalUrl, OwnerID, ShortCode, UrlHash
from link_shortener.infrastructure.database.models.link_model import LinkModel
from link_shortener.infrastructure.database.repositories.sqlalchemy_link_repository import (
    SQLAlchemyLinkRepository,
)
from tests.integration.conftest import ensure_user


@pytest.fixture()
def use_case(app):
    """The wired-up use case, as the CLI command gets it."""
    with app.app_context():
        yield app.container.get_clean_expired_links_use_case()


@pytest.fixture()
def store(app):
    """A repository on its own session, for arranging and checking rows."""
    with app.app_context():
        db_manager = app.container.get_db_manager()
        with db_manager.session() as session:
            yield SQLAlchemyLinkRepository(session), session


def _seed(store, code, ttl=0, last_accessed_days_ago=None):
    """
    Store one link.

    Args:
        store: The ``(repository, session)`` pair.
        code: Short code.
        ttl: Seconds until expiry; negative for already expired, 0 for never.
        last_accessed_days_ago: How long ago it was last clicked.

    Returns:
        The stored Link.
    """
    repo, session = store
    # Foreign keys are enforced on SQLite now, as they always were on
    # PostgreSQL, so the owning account has to exist before a link may name
    # it.
    ensure_user(session, "owner-clean")
    now = datetime.now(timezone.utc)
    # A hash unique to this code, in the only alphabet UrlHash accepts.
    digest = "".join(f"{ord(char):02x}" for char in code).ljust(64, "0")[:64]
    link = Link(
        id=f"clean-{code}",
        url_hash=UrlHash(digest),
        short_code=ShortCode(code),
        original_url=OriginalUrl(f"https://example.com/{code}"),
        created_at=now - timedelta(days=400),
        owner=OwnerID("owner-clean"),
        expires_at=(now + timedelta(seconds=ttl)) if ttl else None,
        last_accessed=(
            now - timedelta(days=last_accessed_days_ago)
            if last_accessed_days_ago is not None
            else None
        ),
    )
    repo.save(link)
    session.commit()
    return link


class TestOnlyExpiredLinksGo:
    """Expiry decides, and nothing else does."""

    def test_a_permanent_link_survives_however_long_it_sat_untouched(
        self, use_case, store
    ):
        _seed(store, "keepaaa", ttl=0, last_accessed_days_ago=400)

        use_case.execute(RequestContext(request_id="cli-test"))

        repo, _ = store
        assert repo.find_by_code(ShortCode("keepaaa")) is not None

    def test_a_never_clicked_permanent_link_survives(self, use_case, store):
        _seed(store, "keepbbb", ttl=0)

        use_case.execute(RequestContext(request_id="cli-test"))

        repo, _ = store
        assert repo.find_by_code(ShortCode("keepbbb")) is not None

    def test_an_expired_link_goes_even_if_clicked_a_moment_ago(
        self, use_case, store
    ):
        _seed(store, "gonecca", ttl=-1, last_accessed_days_ago=0)

        deleted = use_case.execute(RequestContext(request_id="cli-test"))

        repo, _ = store
        assert deleted >= 1
        assert repo.find_by_code(ShortCode("gonecca")) is None

    def test_a_link_still_within_its_ttl_survives(self, use_case, store):
        _seed(store, "keepddd", ttl=3600)

        use_case.execute(RequestContext(request_id="cli-test"))

        repo, _ = store
        assert repo.find_by_code(ShortCode("keepddd")) is not None


class TestABacklogDoesNotWedgeTheSweep:
    """
    The delete names its rows by primary key, one bind parameter each.

    A single statement for the whole backlog hits the driver's parameter
    ceiling -- 32 766 on SQLite, 65 535 on PostgreSQL -- and raises instead
    of deleting anything. That failure feeds itself: nothing is removed, the
    backlog grows, and every later run fails the same way.
    """

    def _seed_bulk(self, session, count, prefix):
        """Store ``count`` already-expired links."""
        now = datetime.now(timezone.utc)
        session.add_all([
            LinkModel(
                id=f"{prefix}-{index}",
                url_hash=f"{index:064x}",
                short_code=f"{prefix[:3]}{index:05d}"[:10],
                original_url="https://example.com/bulk",
                created_at=now,
                clicks=0,
                expires_at=now - timedelta(seconds=1),
            )
            for index in range(count)
        ])
        session.commit()

    def test_the_backlog_is_deleted_in_more_than_one_statement(
        self, app, store, monkeypatch
    ):
        """
        Counted statements rather than seeded rows.

        Proving it with a real backlog means 32 767 rows on SQLite -- the
        ceiling is what breaks, and one row below it nothing does. Shrinking
        the chunk instead exercises the same mechanism: with no chunking at
        all the sweep issues exactly one delete, however many rows there are.
        """
        from sqlalchemy import event

        from link_shortener.infrastructure.database.repositories.sqlalchemy_link_repository import (
            SQLAlchemyLinkRepository,
        )

        _, session = store
        monkeypatch.setattr(SQLAlchemyLinkRepository, "DELETE_CHUNK_SIZE", 10)
        self._seed_bulk(session, 35, "chunk")

        deletes = []

        def record(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("DELETE FROM URLS"):
                deletes.append(statement)

        with app.app_context():
            engine = app.container.get_db_manager().engine
            event.listen(engine, "before_cursor_execute", record)
            try:
                use_case = app.container.get_clean_expired_links_use_case()
                deleted = use_case.execute(RequestContext(request_id="cli-test"))
            finally:
                event.remove(engine, "before_cursor_execute", record)

        assert deleted >= 35
        assert len(deletes) >= 4, f"the whole backlog went in {len(deletes)} statement(s)"
        assert session.query(LinkModel).filter(
            LinkModel.id.like("chunk-%")
        ).count() == 0

    def test_every_row_of_a_multi_chunk_backlog_goes(self, use_case, store):
        from link_shortener.infrastructure.database.repositories.sqlalchemy_link_repository import (
            SQLAlchemyLinkRepository,
        )

        _, session = store
        count = SQLAlchemyLinkRepository.DELETE_CHUNK_SIZE * 2 + 7
        self._seed_bulk(session, count, "bulk")

        deleted = use_case.execute(RequestContext(request_id="cli-test"))

        assert deleted >= count
        assert session.query(LinkModel).filter(
            LinkModel.id.like("bulk-%")
        ).count() == 0


class TestInvalidationHappensAfterTheCommit:
    """
    Until the delete lands, every other connection still sees the rows.

    Dropping cache entries first left a window in which any read refilled
    exactly what the loop had just dropped -- and nothing came back for
    those entries a second time.
    """

    def test_entries_are_dropped_only_once_the_rows_are_gone(self, app, store):
        """
        The order of the two steps is the property, so the order is what is
        recorded. Asking the database what it can see would depend on which
        connection asks and how the driver isolates it -- exactly the thing
        that makes the window hard to notice in the first place.
        """
        from contextlib import contextmanager

        from link_shortener.application.use_cases.admin.links.clean_expired_links import (
            CleanExpiredLinksUseCase,
        )

        _seed(store, "commit1", ttl=-1)
        events = []

        class RecordingUow:
            """Passes everything through, noting when the commit lands."""

            def __init__(self, inner):
                self.inner = inner

            @property
            def links(self):
                return self.inner.links

            def commit(self):
                events.append("commit")
                return self.inner.commit()

        class RecordingCache:
            def delete(self, link):
                events.append("invalidate")
                return True

            def delete_stats(self):
                events.append("invalidate stats")

        with app.app_context():
            inner_factory = app.container.get_uow_factory()

            @contextmanager
            def factory(*args, **kwargs):
                with inner_factory(*args, **kwargs) as uow:
                    yield RecordingUow(uow)

            use_case = CleanExpiredLinksUseCase(
                uow_factory=factory,
                cache=RecordingCache(),
                stats_cache=RecordingCache(),
                logger=app.container.logger_component.get_logger(__name__),
            )
            use_case.execute(RequestContext(request_id="cli-test"))

        assert "invalidate" in events, "the cache was never asked to invalidate"
        assert events.index("commit") < events.index("invalidate"), (
            f"invalidation ran before the rows were gone: {events}"
        )

    def test_an_invalidation_that_did_not_happen_is_reported(self, app, store):
        from link_shortener.application.use_cases.admin.links.clean_expired_links import (
            CleanExpiredLinksUseCase,
        )

        _seed(store, "commit2", ttl=-1)

        class SilentlyFailingCache:
            """A cache that degrades quietly, as the Redis one does."""

            def delete(self, link):
                return False

            def delete_stats(self):
                return None

        warnings = []

        class RecordingLogger:
            def bind(self, **kwargs):
                return self

            def info(self, *args, **kwargs):
                pass

            def warning(self, message, **kwargs):
                warnings.append((message, kwargs))

        with app.app_context():
            use_case = CleanExpiredLinksUseCase(
                uow_factory=app.container.get_uow_factory(),
                cache=SilentlyFailingCache(),
                stats_cache=SilentlyFailingCache(),
                logger=RecordingLogger(),
            )
            use_case.execute(RequestContext(request_id="cli-test"))

        assert warnings, "a skipped invalidation was not reported at all"
        assert warnings[0][1]["not_invalidated"] >= 1
