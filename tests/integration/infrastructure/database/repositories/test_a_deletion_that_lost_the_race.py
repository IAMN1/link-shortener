"""
Tests that an account somebody else has just deleted reads as absent.

`delete` answers `False` for an account that is not there, and the read it
makes to decide that is a hint: it goes stale the moment another
transaction commits, exactly as the address lookup does in `save`.

Measured on the running stack before this was handled -- two simultaneous
`DELETE /api/v1/admin/users/<id>` for one account:

    200  and  500 INTERNAL_SERVER_ERROR

with `StaleDataError: DELETE statement on table 'user_roles' expected to
delete 1 row(s); Only 0 were matched` in the error journal. The second
request flushed a cascade whose rows the first had already taken, and the
service blamed itself for a request that was merely late -- the same
arrangement `save` was given for registrations racing on one address, and
`SQLAlchemyRoleRepository.save` for two creations of one role name. After
the change the same race answers 200 and 404, with or without links on the
account.

The race itself cannot be run here: the suite's database is one in-memory
SQLite connection, and the two transactions this needs do not exist in it.
What is checked is the translation the race depends on -- a stale delete
is an absent account, not an exception out of the repository.
"""

import pytest
from sqlalchemy.orm.exc import StaleDataError

from link_shortener.domain import Email, PasswordHash, Role, User
from link_shortener.infrastructure.database.models.role_model import RoleModel
from link_shortener.infrastructure.database.repositories.sqlalchemy_user_repository import (
    SQLAlchemyUserRepository,
)


HASH = "$2b$12$" + "x" * 53


@pytest.fixture()
def store(app):
    """A user repository and its session."""
    with app.app_context():
        db_manager = app.container.get_db_manager()
        with db_manager.session() as session:
            yield SQLAlchemyUserRepository(session), session


def an_account(store, local_part):
    """
    An account stored through the repository, with a role on it.

    The role matters: what the losing side of the race trips over is the
    cascade into ``user_roles``, so an account wearing nothing would not
    reach the situation at all.
    """
    repo, session = store
    role = session.query(RoleModel).filter_by(name="user").first()
    assert role is not None, "the suite seeds the base roles"

    user = User.create(
        email=Email(f"{local_part}@example.test"),
        password_hash=PasswordHash(HASH),
        roles=[Role(id=role.id, name=role.name)],
    )
    repo.save(user)
    session.commit()
    return user


class TestADeletionThatLostTheRace:

    def test_a_stale_delete_reads_as_an_absent_account(self, store):
        repo, session = store
        user = an_account(store, "lost-the-race")

        original = session.flush

        def flush_as_though_somebody_got_there_first(*args, **kwargs):
            raise StaleDataError(
                "DELETE statement on table 'user_roles' expected to "
                "delete 1 row(s); Only 0 were matched."
            )

        session.flush = flush_as_though_somebody_got_there_first
        try:
            assert repo.delete(user.id) is False
        finally:
            session.flush = original
            session.rollback()

    def test_an_ordinary_deletion_still_answers_true(self, store):
        repo, session = store
        user = an_account(store, "deleted-cleanly")

        assert repo.delete(user.id) is True
        session.commit()
        assert repo.find_by_id(user.id) is None

    def test_an_account_that_was_never_there_answers_false(self, store):
        repo, _ = store

        assert repo.delete("00000000-0000-0000-0000-000000000000") is False
