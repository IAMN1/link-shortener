"""
Tests that deleting an account deletes the links it made.

``urls.owner_id`` was ``ON DELETE SET NULL``, and ``DeleteUserUseCase``
never touched the links at all, so an account could be removed while its
links went on working -- redirecting, counting clicks, and belonging to
nobody. Their creator was gone, so only a holder of ``link:delete_any``
could take them down, and nothing said they were there. The owner of the
project decided the links go with the account, without recovery.

They are deleted by the use case rather than left to the foreign key,
because a row that vanishes behind the application leaves its cache entries
behind: every level would go on answering for a link that no longer exists
for the rest of its TTL, and nothing in the service could clear it.
"""

from datetime import datetime, timezone

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.domain import (
    Link, OriginalUrl, OwnerID, ShortCode, UrlHash
)
from link_shortener.infrastructure.database.models.link_model import LinkModel
from link_shortener.infrastructure.database.models.user_model import UserModel
from link_shortener.infrastructure.database.repositories.sqlalchemy_link_repository import (
    SQLAlchemyLinkRepository,
)
from tests.integration.conftest import ensure_user


OWNER = "owner-being-deleted"
BYSTANDER = "owner-staying"


@pytest.fixture()
def use_case(app):
    """The wired-up use case, as the admin API gets it."""
    with app.app_context():
        yield app.container.get_delete_user_use_case()


@pytest.fixture()
def store(app):
    """A repository on its own session, for arranging and checking rows."""
    with app.app_context():
        db_manager = app.container.get_db_manager()
        with db_manager.session() as session:
            yield SQLAlchemyLinkRepository(session), session


def _seed_link(store, code, owner):
    """
    Store one link under an owner, creating the account if needed.

    Args:
        store: The ``(repository, session)`` pair.
        code: Short code.
        owner: Owning account id, or ``None`` for a guest link.

    Returns:
        The stored Link.
    """
    repo, session = store
    if owner:
        ensure_user(session, owner)

    digest = "".join(f"{ord(char):02x}" for char in code).ljust(64, "0")[:64]
    link = Link(
        id=f"del-{code}",
        url_hash=UrlHash(digest),
        short_code=ShortCode(code),
        original_url=OriginalUrl(f"https://example.com/{code}"),
        created_at=datetime.now(timezone.utc),
        owner=OwnerID(owner) if owner else None,
        guest_identifier=None if owner else "198.51.100.5",
    )
    repo.save(link)
    session.commit()
    return link


def _context():
    return RequestContext(request_id="admin-delete")


class TestTheLinksGoWithTheAccount:

    def test_every_link_the_account_owned_is_deleted(self, use_case, store):
        _, session = store
        _seed_link(store, "gone01", OWNER)
        _seed_link(store, "gone02", OWNER)

        assert use_case.execute(OWNER, _context()) is True

        session.expire_all()
        assert session.query(LinkModel).filter(
            LinkModel.short_code.in_(["gone01", "gone02"])
        ).count() == 0

    def test_the_account_itself_is_gone(self, use_case, store):
        _, session = store
        _seed_link(store, "gone03", OWNER)

        use_case.execute(OWNER, _context())

        session.expire_all()
        assert session.get(UserModel, OWNER) is None

    def test_nobody_elses_links_are_touched(self, use_case, store):
        _, session = store
        _seed_link(store, "gone04", OWNER)
        _seed_link(store, "stays1", BYSTANDER)
        _seed_link(store, "stays2", None)

        use_case.execute(OWNER, _context())

        session.expire_all()
        survivors = {
            row.short_code
            for row in session.query(LinkModel).filter(
                LinkModel.short_code.in_(["gone04", "stays1", "stays2"])
            )
        }
        assert survivors == {"stays1", "stays2"}

    def test_an_account_with_no_links_still_deletes(self, use_case, store):
        _, session = store
        ensure_user(session, "owner-empty")
        session.commit()

        assert use_case.execute("owner-empty", _context()) is True

    def test_deleting_an_account_that_is_not_there_answers_false(
        self, use_case
    ):
        assert use_case.execute("never-existed", _context()) is False


class TestNoLinkIsLeftOwnerless:
    """
    The state the old behaviour produced: a live link with no owner and no
    guest identifier, which its creator could not delete because they no
    longer existed.
    """

    def test_no_orphan_row_survives_the_deletion(self, use_case, store):
        _, session = store
        _seed_link(store, "orph01", OWNER)

        use_case.execute(OWNER, _context())

        session.expire_all()
        orphans = session.query(LinkModel).filter(
            LinkModel.short_code == "orph01"
        ).all()
        assert orphans == []
