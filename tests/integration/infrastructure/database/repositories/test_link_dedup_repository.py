"""
Repository-level tests for the deduplication lookup and expiry cleanup.

Written against a real SQLite database rather than a mocked repository: the
behaviour under test is which rows a query selects, and a mock cannot be
wrong about that.
"""

from datetime import datetime, timedelta, timezone

import pytest

from link_shortener.domain import (
    DedupScope, Link, LinkConflictError, OriginalUrl, OwnerID, ShortCode,
    UrlHash
)
from link_shortener.infrastructure.database.repositories.sqlalchemy_link_repository import (
    SQLAlchemyLinkRepository,
)
from tests.integration.conftest import ensure_user


HASH = UrlHash("d" * 64)
OTHER_HASH = UrlHash("e" * 64)


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


def _link(
    code, url_hash=HASH, owner=None, guest=None, ttl=0, created_offset=0
):
    """
    Build a link for the tests.

    Args:
        code: Short code.
        url_hash: Hash the link is filed under.
        owner: Owner id, or ``None`` for an owner-less link.
        guest: Guest identifier, or ``None``.
        ttl: Seconds until expiry; negative for an already-expired link.
        created_offset: Seconds to shift ``created_at`` by.

    Returns:
        A Link entity.
    """
    global _counter
    _counter += 1
    now = datetime.now(timezone.utc)
    return Link(
        id=f"dedup-{_counter}",
        url_hash=url_hash,
        short_code=ShortCode(code),
        original_url=OriginalUrl("https://example.com/dedup"),
        created_at=now + timedelta(seconds=created_offset),
        owner=OwnerID(owner) if owner else None,
        expires_at=(now + timedelta(seconds=ttl)) if ttl else None,
        guest_identifier=guest,
    )


class TestDeduplicationStaysInsideItsScope:
    """One caller's link must never answer for another's."""

    def test_another_users_link_is_not_returned(self, repo):
        repo.save(_link("dedup01", owner="user-a"))

        found = repo.find_live_by_hash(HASH, DedupScope.for_owner("user-b"))

        assert found is None

    def test_own_link_is_returned(self, repo):
        repo.save(_link("dedup02", url_hash=OTHER_HASH, owner="user-c"))

        found = repo.find_live_by_hash(
            OTHER_HASH, DedupScope.for_owner("user-c")
        )

        assert found is not None
        assert found.short_code.value == "dedup02"

    def test_a_guest_does_not_inherit_a_registered_users_link(self, repo):
        repo.save(_link("dedup03", owner="user-d"))

        found = repo.find_live_by_hash(HASH, DedupScope.for_guest("10.0.0.1"))

        assert found is None

    def test_a_guest_does_not_inherit_another_guests_link(self, repo):
        repo.save(_link("dedup04", guest="10.0.0.2"))

        found = repo.find_live_by_hash(HASH, DedupScope.for_guest("10.0.0.3"))

        assert found is None

    def test_the_same_guest_gets_their_own_link_back(self, repo):
        repo.save(_link("dedup05", guest="10.0.0.4"))

        found = repo.find_live_by_hash(HASH, DedupScope.for_guest("10.0.0.4"))

        assert found is not None
        assert found.short_code.value == "dedup05"

    def test_an_owned_link_never_answers_for_the_anonymous_scope(self, repo):
        repo.save(_link("dedup06", owner="user-e"))

        found = repo.find_live_by_hash(HASH, DedupScope())

        assert found is None

    def test_the_oldest_match_wins(self, repo):
        repo.save(_link("dedup07", owner="user-f", created_offset=-60))
        repo.save(_link("dedup08", owner="user-f", created_offset=-10))

        found = repo.find_live_by_hash(HASH, DedupScope.for_owner("user-f"))

        assert found.short_code.value == "dedup07"


class TestExpiredLinksAreNotDeduplicatedAgainst:
    """
    An expired link must not be handed back as an existing one.

    Doing so returned a code that answers 410 -- and, because nothing else
    creates a replacement while the expired row is still findable, made the
    URL permanently unshortenable for that caller.
    """

    def test_an_expired_link_is_not_returned(self, repo):
        repo.save(_link("dedup09", owner="user-g", ttl=-60))

        found = repo.find_live_by_hash(HASH, DedupScope.for_owner("user-g"))

        assert found is None

    def test_a_live_link_alongside_an_expired_one_is_returned(self, repo):
        repo.save(_link("dedup10", owner="user-h", ttl=-60, created_offset=-60))
        repo.save(_link("dedup11", owner="user-h", ttl=3600))

        found = repo.find_live_by_hash(HASH, DedupScope.for_owner("user-h"))

        assert found.short_code.value == "dedup11"

    def test_bulk_lookup_applies_the_same_two_rules(self, repo):
        repo.save(_link("dedup12", owner="user-i", ttl=-60))
        repo.save(_link("dedup13", url_hash=OTHER_HASH, owner="user-j"))

        result = repo.find_live_by_hashes(
            [HASH, OTHER_HASH], DedupScope.for_owner("user-i")
        )

        assert result[HASH] is None          # expired
        assert result[OTHER_HASH] is None    # someone else's


class TestCleanupDeletesByExpiryAlone:
    """
    ``delete_expired`` may look at nothing but ``expires_at``.

    The command used to sweep by ``last_accessed``, which deleted permanent
    links nobody had clicked and kept the expired ones it was named after.
    """

    def test_a_permanent_link_is_kept_however_stale(self, repo):
        link = _link("clean01", url_hash=UrlHash("1" * 64))
        link.last_accessed = datetime.now(timezone.utc) - timedelta(days=400)
        repo.save(link)

        deleted = repo.delete_expired(datetime.now(timezone.utc))

        assert link.short_code not in [d.short_code for d in deleted]
        assert repo.find_by_code(ShortCode("clean01")) is not None

    def test_an_expired_link_is_deleted_however_fresh(self, repo):
        link = _link("clean02", url_hash=UrlHash("2" * 64), ttl=-1)
        link.last_accessed = datetime.now(timezone.utc)
        repo.save(link)

        deleted = repo.delete_expired(datetime.now(timezone.utc))

        assert ShortCode("clean02") in [d.short_code for d in deleted]
        assert repo.find_by_code(ShortCode("clean02")) is None

    def test_a_link_that_has_not_expired_yet_is_kept(self, repo):
        repo.save(_link("clean03", url_hash=UrlHash("3" * 64), ttl=3600))

        repo.delete_expired(datetime.now(timezone.utc))

        assert repo.find_by_code(ShortCode("clean03")) is not None

    def test_entities_are_returned_so_the_cache_can_be_invalidated(self, repo):
        repo.save(
            _link("clean04", url_hash=UrlHash("4" * 64), ttl=-1, guest="10.0.0.9")
        )

        deleted = repo.delete_expired(datetime.now(timezone.utc))

        entry = next(d for d in deleted if d.short_code.value == "clean04")
        # A code alone cannot name the deduplication key; the hash and the
        # scope can only come from the entity.
        assert entry.url_hash == UrlHash("4" * 64)
        assert entry.dedup_scope() == DedupScope.for_guest("10.0.0.9")


class TestAClaimedCodeIsReportedAsAConflict:
    """
    The unique index is the authority on whether a code is free.

    A lookup before the insert is a hint that goes stale the moment another
    transaction commits, so storage has to be able to say "somebody got
    there first" in terms the domain understands. Letting the driver's
    ``IntegrityError`` escape instead is what turned an ordinary race -- a
    double-click -- into a 500.
    """

    def test_reusing_a_short_code_raises_a_domain_error(self, repo):
        repo.save(_link("conf001", url_hash=UrlHash("7" * 64)))

        with pytest.raises(LinkConflictError):
            repo.save(_link("conf001", url_hash=UrlHash("8" * 64)))

        # The session is unusable from here on, which is why the retry runs
        # in a fresh unit of work rather than reusing this one.
        repo.session.rollback()

    def test_a_bulk_insert_reports_it_too(self, repo):
        repo.save(_link("conf002", url_hash=UrlHash("9" * 64)))

        with pytest.raises(LinkConflictError):
            repo.save_many([_link("conf002", url_hash=UrlHash("a" * 63 + "b"))])

        repo.session.rollback()


class TestSaveUpdates:
    """``save`` promises "new or updated" and has to keep both halves."""

    def test_saving_a_stored_link_again_updates_it(self, repo):
        link = _link("upd001", url_hash=UrlHash("5" * 64))
        repo.save(link)

        link.clicks = 7
        link.expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        repo.save(link)

        stored = repo.find_by_code(ShortCode("upd001"))
        assert stored.clicks == 7
        assert stored.expires_at is not None

    def test_saving_twice_does_not_create_a_second_row(self, repo):
        link = _link("upd002", url_hash=UrlHash("6" * 64), owner="user-k")
        repo.save(link)
        repo.save(link)

        result = repo.find_live_by_hashes(
            [UrlHash("6" * 64)], DedupScope.for_owner("user-k")
        )
        assert result[UrlHash("6" * 64)].id == link.id
        assert len(repo.find_by_owner("user-k")) == 1
