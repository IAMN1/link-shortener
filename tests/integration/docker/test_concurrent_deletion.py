"""
Deleting one link twice at once, against real PostgreSQL.

``delete()`` answers from the statement, not from a read preceding it:
fetching the row, deleting it and returning ``True`` because the fetch found
something is wrong under READ COMMITTED, where two concurrent deletions both
see the
row in their own snapshot, both issue a DELETE, and only one of them matches
anything -- yet both reported success.

What that cost is not the row, which is removed exactly once either way. It
is the answer and the record: ten simultaneous requests answered
``200 {"message": "Link deleted"}`` ten times over one link, and each of
them wrote its own "link deleted" line into the audit trail and dropped the
statistics cache. A caller could not tell from the status whether *they*
had deleted it.

SQLite serialises writers, so the suite's in-memory database cannot show
this. These run against the throwaway PostgreSQL stack, with threads,
because the property is about two transactions overlapping.
"""

import threading
import uuid
from datetime import datetime, timezone

import pytest

from link_shortener.domain import Link, OriginalUrl, ShortCode, UrlHash
from link_shortener.infrastructure.database.repositories.sqlalchemy_link_repository import (
    SQLAlchemyLinkRepository,
)


WORKERS = 8


def _make_link():
    """Build a link with a unique hash and code."""
    token = uuid.uuid4().hex
    return Link(
        id=str(uuid.uuid4()),
        url_hash=UrlHash(token + token[:32]),
        short_code=ShortCode(f"d{token[:8]}"),
        original_url=OriginalUrl(f"https://example.com/{token}"),
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture()
def stored_link(app, pg_session_factory):
    """One link, committed and waiting to be deleted.

    ``app`` is requested for its schema: it is the fixture that creates the
    tables on the PostgreSQL stack.
    """
    link = _make_link()
    session = pg_session_factory()
    SQLAlchemyLinkRepository(session).save(link)
    session.commit()
    session.close()
    return link


def _delete_concurrently(session_factory, link_id):
    """Fire ``WORKERS`` deletions of one row at once and collect the answers."""
    answers = []
    barrier = threading.Barrier(WORKERS)

    def worker():
        barrier.wait()
        session = session_factory()
        try:
            answers.append(SQLAlchemyLinkRepository(session).delete(link_id))
            session.commit()
        except Exception as error:  # noqa: BLE001 - recorded, not handled
            session.rollback()
            answers.append(f"error:{type(error).__name__}")
        finally:
            session.close()

    threads = [threading.Thread(target=worker) for _ in range(WORKERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return answers


class TestTheAnswerComesFromTheStatement:
    """
    The mechanism on its own, without racing the scheduler for it.

    One session reads the row -- which is what the old implementation did
    before deleting, and which puts the object in that session's identity
    map, so a later ``session.get`` answers from memory without asking the
    database. Another session deletes it and commits. The first session then
    deletes: it holds an object that no longer has a row, and reporting
    success on the strength of having seen it is the defect.
    """

    def test_deleting_a_row_somebody_else_removed_reports_false(
        self, app, pg_session_factory, stored_link
    ):
        watcher = pg_session_factory()
        remover = pg_session_factory()
        try:
            seen = SQLAlchemyLinkRepository(watcher).find_by_code(
                stored_link.short_code
            )
            assert seen is not None

            assert SQLAlchemyLinkRepository(remover).delete(stored_link.id) is True
            remover.commit()

            assert SQLAlchemyLinkRepository(watcher).delete(stored_link.id) is False
        finally:
            watcher.close()
            remover.close()


class TestOnlyOneDeletionSucceeds:

    def test_exactly_one_call_reports_that_it_deleted_the_row(
        self, pg_session_factory, stored_link
    ):
        answers = _delete_concurrently(pg_session_factory, stored_link.id)

        assert answers.count(True) == 1, answers
        assert answers.count(False) == WORKERS - 1, answers

    def test_the_row_is_gone(self, pg_session_factory, stored_link):
        _delete_concurrently(pg_session_factory, stored_link.id)

        session = pg_session_factory()
        try:
            found = SQLAlchemyLinkRepository(session).find_by_code(
                stored_link.short_code
            )
        finally:
            session.close()

        assert found is None

    def test_a_sequential_second_deletion_also_reports_false(
        self, pg_session_factory, stored_link
    ):
        """The same rule without any concurrency, so it is stated plainly."""
        session = pg_session_factory()
        repo = SQLAlchemyLinkRepository(session)
        try:
            assert repo.delete(stored_link.id) is True
            session.commit()
            assert repo.delete(stored_link.id) is False
        finally:
            session.close()
