"""Integration tests for SQLAlchemyLinkRepository with real in-memory DB."""

import pytest
from datetime import datetime, timedelta, timezone
from link_shortener.domain.entities.link import Link
from link_shortener.domain.value_objects.original_url import OriginalUrl
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.domain.value_objects.url_hash import UrlHash
from link_shortener.domain.value_objects.dedup_scope import DedupScope
from link_shortener.domain.value_objects.owner_id import OwnerID
from link_shortener.infrastructure.database.repositories.sqlalchemy_link_repository import (
    SQLAlchemyLinkRepository,
)
from tests.integration.conftest import ensure_user
from link_shortener.infrastructure.database.unit_of_work import SQLAlchemyUnitOfWork


class _RepoThatCreatesOwners(SQLAlchemyLinkRepository):
    """
    A repository that inserts the owning account before it saves a link.

    Foreign keys are enforced on SQLite now, as they always were on
    PostgreSQL, so a link cannot name an account that does not exist. The
    tests below are about which rows a query selects, not about account
    creation, so the account is made here rather than in every case.
    """

    def save(self, link):
        if link.owner:
            ensure_user(self.session, link.owner.value)
        return super().save(link)

    def save_many(self, links):
        for link in links:
            if link.owner:
                ensure_user(self.session, link.owner.value)
        return super().save_many(links)


@pytest.fixture()
def repo(app):
    """Provide a link repository bound to the in-memory DB."""
    with app.app_context():
        db_manager = app.container.get_db_manager()
        with db_manager.session() as session:
            yield _RepoThatCreatesOwners(session)


_counter = 0

def _make_link(code="test0001", url="https://example.com", owner=None, ttl=0):
    global _counter
    _counter += 1
    # UrlHash requires exactly 64 lowercase hex chars; ShortCode requires 6-10 chars
    hex_suffix = f"{_counter:04x}"
    return Link.create(
        url_hash=UrlHash("a" * 60 + hex_suffix),
        short_code=ShortCode(code),
        original_url=OriginalUrl(url),
        owner=OwnerID(owner) if owner else None,
        ttl_seconds=ttl,
    )


class TestLinkRepositoryCRUD:
    """Test save, find, delete operations against real SQLite."""

    def test_save_and_find_by_code(self, repo):
        link = _make_link("repo0001")
        repo.save(link)

        found = repo.find_by_code(ShortCode("repo0001"))
        assert found is not None
        assert found.short_code.value == "repo0001"
        assert found.original_url.value == "https://example.com"

    def test_find_by_code_returns_none(self, repo):
        found = repo.find_by_code(ShortCode("noexist"))
        assert found is None

    def test_save_and_find_by_hash(self, repo):
        link = _make_link("repo0002")
        repo.save(link)

        found = repo.find_live_by_hash(link.url_hash, link.dedup_scope())
        assert found is not None
        assert found.short_code.value == "repo0002"

    def test_delete_by_id(self, repo):
        link = _make_link("repo0003")
        saved = repo.save(link)

        repo.delete(saved.id)

        found = repo.find_by_code(ShortCode("repo0003"))
        assert found is None

    def test_delete_reports_a_missing_row(self, repo):
        assert repo.delete("no-such-link-id") is False

    def test_increment_clicks(self, repo):
        link = _make_link("repo0004")
        repo.save(link)

        updated = repo.increment_clicks(ShortCode("repo0004"))
        assert updated.clicks == 1
        assert updated.last_accessed is not None

        updated2 = repo.increment_clicks(ShortCode("repo0004"))
        assert updated2.clicks == 2

    def test_increment_clicks_nonexistent(self, repo):
        with pytest.raises(Exception):
            repo.increment_clicks(ShortCode("noexist"))

    def test_count_guest_links(self, repo):
        link1 = _make_link("guest001", owner=None)
        link1.guest_identifier = "192.168.1.1"
        repo.save(link1)

        link2 = _make_link("guest002", owner=None)
        link2.guest_identifier = "192.168.1.1"
        repo.save(link2)

        link3 = _make_link("guest003", owner=None)
        link3.guest_identifier = "10.0.0.1"
        repo.save(link3)

        count = repo.count_guest_links_by_identifier("192.168.1.1", since_days=7)
        assert count == 2

    def test_find_by_owner(self, repo):
        link1 = _make_link("owner01", owner="user-abc")
        repo.save(link1)
        link2 = _make_link("owner02", owner="user-abc")
        repo.save(link2)
        link3 = _make_link("owner03", owner="user-xyz")
        repo.save(link3)

        results = repo.find_by_owner("user-abc")
        assert len(results) == 2
        codes = {l.short_code.value for l in results}
        assert codes == {"owner01", "owner02"}


class TestUnitOfWorkIntegration:
    """Test UnitOfWork commit/rollback with real DB."""

    def test_commit_persists_data(self, app):
        with app.app_context():
            db_manager = app.container.get_db_manager()

            with SQLAlchemyUnitOfWork(db_manager) as uow:
                link = _make_link("uow0001")
                uow.links.save(link)
                uow.commit()

            with SQLAlchemyUnitOfWork(db_manager, read_only=True) as uow:
                found = uow.links.find_by_code(ShortCode("uow0001"))
                assert found is not None

    def test_rollback_discards_data(self, app):
        with app.app_context():
            db_manager = app.container.get_db_manager()

            with SQLAlchemyUnitOfWork(db_manager) as uow:
                link = _make_link("uow0002")
                uow.links.save(link)

            with SQLAlchemyUnitOfWork(db_manager, read_only=True) as uow:
                found = uow.links.find_by_code(ShortCode("uow0002"))
                assert found is None


class TestDeletionReportsWhatItActuallyDid:
    """
    ``delete()`` answered from a read that preceded the statement, not from
    the statement. Under READ COMMITTED two concurrent deletions both see
    the row in their own snapshot, both issue a DELETE, and only one matches
    anything -- while the other reported success too. Ten simultaneous
    requests answered 200 ten times over one row, and each wrote its own
    "link deleted" line into the audit trail.
    """

    def test_deleting_a_row_reports_true_once(self, repo):
        link = _make_link(code="delrep1")
        repo.save(link)

        assert repo.delete(link.id) is True

    def test_deleting_it_again_reports_false(self, repo):
        link = _make_link(code="delrep2")
        repo.save(link)
        repo.delete(link.id)

        assert repo.delete(link.id) is False

    def test_deleting_something_that_never_existed_reports_false(self, repo):
        assert repo.delete("no-such-link") is False
