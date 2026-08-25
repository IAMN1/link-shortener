"""
Tests that an administrative write outrun by a deletion says what is gone.

`save` reads the account and its roles before it writes them, and both
reads are hints: they go stale the moment another transaction commits.
Two of those races were measured on the running stack, and both were
answered 500 -- the service blaming itself for a request that was merely
late, which is the arrangement `delete` was given for two simultaneous
deletions.

`POST /api/v1/admin/users/<id>/deactivate` against a simultaneous
`DELETE` of the same account, three attempts:

    200 / 200,  500 / 200,  500 / 200

with `StaleDataError: UPDATE statement on table 'users' expected to
update 1 row(s); 0 were matched`. The same race reached `PUT
/users/<id>/roles` two milliseconds behind the delete.

`PUT /api/v1/admin/users/<id>/roles` naming a role, against a `DELETE
/api/v1/admin/roles/<name>` of that role two milliseconds later:

    500 / 200

with `ForeignKeyViolation: insert or update on table "user_roles"`. That
is the situation `_sync_roles` already answers `RoleNotFoundError` for --
a role deleted between another administrator's lookup and their save --
reached a moment later than the lookup can see.

Neither race can be run here: the suite's database is one in-memory
SQLite connection, and the two transactions they need do not exist in it.
What is checked is the translation each race depends on -- a stale write
is an absent account, a role the association cannot point at is an absent
role, and a violation from anywhere else is still nobody's answer to give.
"""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from link_shortener.domain import (
    Email, PasswordHash, Role, RoleNotFoundError, User, UserNotFoundError,
)
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
    """An account stored through the repository, wearing a role."""
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


class Diagnostics:
    """What PostgreSQL says about a violation, in the shape psycopg gives.

    Only the two fields the repository reads. Written out rather than
    provoked, because provoking it needs the second transaction this
    database does not have.
    """

    def __init__(self, table_name, message_detail):
        self.table_name = table_name
        self.message_detail = message_detail


class Refusal(Exception):
    """A driver error carrying diagnostics, as psycopg's does."""

    def __init__(self, diag):
        super().__init__("insert or update violates foreign key constraint")
        self.diag = diag


def a_foreign_key_violation(table_name, key_id):
    """An integrity error shaped like the one the race provokes."""
    return IntegrityError(
        "INSERT INTO user_roles",
        {},
        Refusal(Diagnostics(
            table_name,
            f'Key (role_id)=({key_id}) is not present in table "roles".',
        )),
    )


def flushing_raises(session, error):
    """Make the next flush fail the way the losing side of a race does."""
    original = session.flush

    def flush(*args, **kwargs):
        raise error

    session.flush = flush
    return original


class TestAnAccountDeletedUnderTheWrite:

    def test_a_stale_write_is_an_absent_account(self, store):
        repo, session = store
        user = an_account(store, "written-too-late")
        user.deactivate()

        original = flushing_raises(session, StaleDataError(
            "UPDATE statement on table 'users' expected to update 1 "
            "row(s); 0 were matched."
        ))
        try:
            with pytest.raises(UserNotFoundError) as refusal:
                repo.save(user)
        finally:
            session.flush = original
            session.rollback()

        assert refusal.value.code == "USER_NOT_FOUND"
        assert refusal.value.user_id == user.id

    def test_an_ordinary_write_still_goes_through(self, store):
        repo, session = store
        user = an_account(store, "written-in-time")

        user.deactivate()
        repo.save(user)
        session.commit()

        assert repo.find_by_id(user.id).is_active is False


class TestARoleDeletedUnderTheWrite:

    def test_a_role_the_association_cannot_reach_is_an_absent_role(
        self, store
    ):
        repo, session = store
        user = an_account(store, "re-roled-too-late")
        vanished = user.roles[0]

        original = flushing_raises(
            session, a_foreign_key_violation("user_roles", vanished.id)
        )
        try:
            with pytest.raises(RoleNotFoundError) as refusal:
                repo.save(user)
        finally:
            session.flush = original
            session.rollback()

        assert refusal.value.code == "ROLE_NOT_FOUND"
        assert refusal.value.role_name == vanished.name

    def test_a_violation_from_another_table_is_still_re_raised(self, store):
        """
        The discipline `_is_email_clash` was given, for the same reason:
        a wrong answer is worse than an unhandled one. 500 says the
        service does not know what happened, and anything else here would
        be saying it knows something untrue.
        """
        repo, session = store
        user = an_account(store, "violated-elsewhere")

        original = flushing_raises(
            session,
            a_foreign_key_violation("some_other_table", user.roles[0].id),
        )
        try:
            with pytest.raises(IntegrityError):
                repo.save(user)
        finally:
            session.flush = original
            session.rollback()

    def test_a_violation_naming_a_role_this_write_never_carried(self, store):
        """
        The right table and a key that is none of this account's roles.
        Matched back to what the write was carrying rather than taken on
        the table's word, so a violation the repository cannot explain
        stays unexplained.
        """
        repo, session = store
        user = an_account(store, "violated-for-a-stranger")

        original = flushing_raises(
            session,
            a_foreign_key_violation(
                "user_roles", "00000000-0000-0000-0000-0000000000ff"
            ),
        )
        try:
            with pytest.raises(IntegrityError):
                repo.save(user)
        finally:
            session.flush = original
            session.rollback()

    def test_a_database_that_reports_no_diagnostics_is_re_raised(self, store):
        """
        SQLite names the column in the message and offers no diagnostics
        at all, so there is nothing to match a role against and nothing
        to say about which one went.
        """
        repo, session = store
        user = an_account(store, "violated-without-diagnostics")

        original = flushing_raises(
            session,
            IntegrityError(
                "INSERT INTO user_roles", {},
                Exception("FOREIGN KEY constraint failed"),
            ),
        )
        try:
            with pytest.raises(IntegrityError):
                repo.save(user)
        finally:
            session.flush = original
            session.rollback()
