"""
The guest allowance under real concurrency, against real PostgreSQL.

Counting links and then inserting one is two statements. Without something
tying them together, simultaneous requests from one guest each read the same
allowance and each spend it in full: five concurrent batches produced fifty
links against a limit of ten, and unlike a rate limit, the overshoot is
permanent -- the rows stay.

SQLite cannot express the lock that fixes this, so the suite's in-memory
database would report success either way. These tests therefore run against
the throwaway PostgreSQL stack, and they use threads rather than a mocked
sequence: the property is about two transactions overlapping, and nothing
that serialises them can demonstrate it.
"""

import threading
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from link_shortener.domain import Link, OriginalUrl, ShortCode, UrlHash
from link_shortener.infrastructure.database.repositories.sqlalchemy_link_repository import (
    SQLAlchemyLinkRepository,
)


LIMIT = 10
WORKERS = 8


def _make_link(identifier, index):
    """Build a guest link with a unique hash and code."""
    token = uuid.uuid4().hex
    return Link(
        id=str(uuid.uuid4()),
        url_hash=UrlHash(token + token[:32]),
        short_code=ShortCode(f"q{index:04d}{token[:4]}"[:10]),
        original_url=OriginalUrl(f"https://example.com/{token}"),
        created_at=datetime.now(timezone.utc),
        guest_identifier=identifier,
    )


def _attempt(session_factory, identifier, index, results, serialise):
    """Run one guest creation the way the use case does.

    Args:
        session_factory: Factory for a session on its own connection.
        identifier: Guest identifier.
        index: Worker number, for a unique code.
        results: List to append the outcome to.
        serialise: Whether to take the quota lock, as the use case does.
    """
    session = session_factory()
    try:
        repo = SQLAlchemyLinkRepository(session)
        if serialise:
            repo.lock_guest_quota(identifier)
        used = repo.count_guest_links_by_identifier(identifier, 1)
        if used >= LIMIT:
            results.append("refused")
            session.rollback()
            return
        repo.save(_make_link(identifier, index))
        session.commit()
        results.append("created")
    except Exception as error:  # noqa: BLE001 - recorded, not handled
        session.rollback()
        results.append(f"error:{type(error).__name__}")
    finally:
        session.close()


def _run_concurrently(session_factory, identifier, serialise):
    """Fire ``WORKERS`` creations at once and return their outcomes."""
    results = []
    barrier = threading.Barrier(WORKERS)

    def worker(index):
        barrier.wait()
        _attempt(session_factory, identifier, index, results, serialise)

    threads = [
        threading.Thread(target=worker, args=(index,)) for index in range(WORKERS)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


@pytest.fixture()
def near_the_limit(app, pg_session_factory):
    """A guest with exactly one slot left of their allowance."""
    identifier = f"198.51.100.{uuid.uuid4().int % 200}"
    session = pg_session_factory()
    repo = SQLAlchemyLinkRepository(session)
    for index in range(LIMIT - 1):
        repo.save(_make_link(identifier, index))
    session.commit()
    session.close()
    return identifier


class TestTheAllowanceIsSpentOnce:
    """Simultaneous requests must not each spend the same last slot."""

    def test_only_one_of_many_simultaneous_requests_gets_the_last_slot(
        self, pg_session_factory, near_the_limit
    ):
        results = _run_concurrently(pg_session_factory, near_the_limit, True)

        assert results.count("created") == 1, results
        assert results.count("refused") == WORKERS - 1, results

    def test_the_stored_count_never_exceeds_the_limit(
        self, pg_session_factory, near_the_limit
    ):
        _run_concurrently(pg_session_factory, near_the_limit, True)

        session = pg_session_factory()
        try:
            stored = SQLAlchemyLinkRepository(
                session
            ).count_guest_links_by_identifier(near_the_limit, 1)
        finally:
            session.close()

        assert stored == LIMIT

    def test_without_the_lock_the_allowance_is_overspent(
        self, pg_session_factory, near_the_limit
    ):
        """
        The same run with the lock removed, so the test proves the lock is
        what does the work rather than the scheduler being kind.
        """
        results = _run_concurrently(pg_session_factory, near_the_limit, False)

        assert results.count("created") > 1, (
            "the race did not reproduce; the test above proves nothing"
        )


class TestGuestsDoNotWaitOnEachOther:
    """The lock is per identifier, not a global gate on link creation."""

    def test_two_identifiers_hold_the_lock_at_the_same_time(
        self, app, pg_session_factory
    ):
        first, second = "203.0.113.61", "203.0.113.62"
        holding = threading.Event()
        released = threading.Event()
        outcome = []

        def hold():
            session = pg_session_factory()
            try:
                SQLAlchemyLinkRepository(session).lock_guest_quota(first)
                holding.set()
                released.wait(timeout=5)
                session.rollback()
            finally:
                session.close()

        holder = threading.Thread(target=hold)
        holder.start()
        holding.wait(timeout=5)

        session = pg_session_factory()
        try:
            # Would block until the holder gives up if the lock were global.
            session.execute(text("SET LOCAL lock_timeout = '2s'"))
            SQLAlchemyLinkRepository(session).lock_guest_quota(second)
            outcome.append("acquired")
        finally:
            session.rollback()
            session.close()
            released.set()
            holder.join()

        assert outcome == ["acquired"]
