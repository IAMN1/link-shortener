"""
Tests that a role somebody else has just changed reads as absent.

Both `save` and `delete` read the role before writing it, and both reads
are hints: they go stale the moment another transaction commits.
Measured on the running stack -- `PUT
/api/v1/admin/roles/<name>/permissions` and a `DELETE` of the same role
two milliseconds later:

    200  and  500 INTERNAL_SERVER_ERROR

with `StaleDataError: DELETE statement on table 'role_permissions'
expected to delete 1 row(s); Only 0 were matched` in the error journal.
The deletion flushed a cascade whose rows the permission change had
already replaced, and the service blamed itself for a request that was
merely late -- the same arrangement both writes in
`SQLAlchemyUserRepository` were given for their own races.

The pair loses both ways round. With the deletion answered, a finer grid
over the shift put the write on the losing side instead: 500 twice with
the same error, and once `409 ROLE_ALREADY_EXISTS` for a request that
asks to take no name at all. After the change the race answers 200 and
404 whichever side arrives late.

Neither side's race can be run here, for the reason the user
repository's cannot: the suite's database is one in-memory SQLite
connection. What is checked is the translation each depends on -- a
stale write is an absent role, and so is an association that cannot find
the role it points at.
"""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from link_shortener.domain import (
    Role, RoleAlreadyExistsError, RoleNotFoundError,
)
from link_shortener.infrastructure.database.repositories.sqlalchemy_role_repository import (
    SQLAlchemyRoleRepository,
)


@pytest.fixture()
def store(app):
    """A role repository and its session."""
    with app.app_context():
        db_manager = app.container.get_db_manager()
        with db_manager.session() as session:
            yield SQLAlchemyRoleRepository(session), session


def a_role(store, name):
    """A deletable role, stored through the repository."""
    repo, session = store
    saved = repo.save(
        Role(id=str(uuid.uuid4()), name=name, description="probe")
    )
    session.commit()
    return saved


class TestARoleDeletionThatLostTheRace:

    def test_a_stale_delete_reads_as_an_absent_role(self, store):
        repo, session = store
        role = a_role(store, "lost-the-race")

        original = session.flush

        def flush_as_though_somebody_got_there_first(*args, **kwargs):
            raise StaleDataError(
                "DELETE statement on table 'role_permissions' expected "
                "to delete 1 row(s); Only 0 were matched."
            )

        session.flush = flush_as_though_somebody_got_there_first
        try:
            with pytest.raises(RoleNotFoundError) as refusal:
                repo.delete(role.id)
        finally:
            session.flush = original
            session.rollback()

        assert refusal.value.code == "ROLE_NOT_FOUND"
        assert refusal.value.role_name == "lost-the-race"

    def test_an_ordinary_deletion_still_goes_through(self, store):
        repo, session = store
        role = a_role(store, "deleted-cleanly")

        repo.delete(role.id)
        session.commit()

        assert repo.get_by_name("deleted-cleanly") is None

    def test_a_role_that_was_never_there_is_not_an_error(self, store):
        """
        Unchanged: this port answers ``None``, and the service above
        raises for a name it could not read, so the absence is decided
        one level up and always has been.
        """
        repo, _ = store

        assert repo.delete("00000000-0000-0000-0000-000000000000") is None


class Diagnostics:
    """What PostgreSQL says about a violation, in the shape psycopg gives.

    Only the two fields the repository reads; provoking the real thing
    needs the second transaction this database does not have.
    """

    def __init__(self, table_name, message_detail):
        self.table_name = table_name
        self.message_detail = message_detail


class Refusal(Exception):
    """A driver error carrying diagnostics, as psycopg's does."""

    def __init__(self, diag):
        super().__init__("violates foreign key constraint")
        self.diag = diag


def flushing_raises(session, error):
    """Make the next flush fail the way the losing side of a race does."""
    original = session.flush

    def flush(*args, **kwargs):
        raise error

    session.flush = flush
    return original


class TestARoleChangeThatLostTheRace:
    """The other side of it: the write, rather than the deletion.

    Both were measured on the running stack, in one probe over a fine
    grid of shifts between the two requests -- ``PUT
    /api/v1/admin/roles/<name>/permissions`` against a ``DELETE`` of that
    role. Landing inside the window, the permission change answered
    **500** twice with `StaleDataError` on ``role_permissions``, and
    **409 ROLE_ALREADY_EXISTS** once, for a request that asks to take no
    name at all -- the broad catch reading a foreign key violation as the
    unique one. `docs/decisions.md` had recorded that catch as a mine
    nothing could reach; a race reaches it.
    """

    def test_a_stale_write_is_an_absent_role(self, store):
        repo, session = store
        role = a_role(store, "written-too-late")

        original = flushing_raises(session, StaleDataError(
            "DELETE statement on table 'role_permissions' expected to "
            "delete 1 row(s); Only 0 were matched."
        ))
        try:
            with pytest.raises(RoleNotFoundError) as refusal:
                repo.save(role)
        finally:
            session.flush = original
            session.rollback()

        assert refusal.value.role_name == "written-too-late"

    def test_an_association_that_cannot_find_its_role_is_an_absent_role(
        self, store
    ):
        repo, session = store
        role = a_role(store, "association-orphaned")

        original = flushing_raises(session, IntegrityError(
            "INSERT INTO role_permissions", {},
            Refusal(Diagnostics(
                "role_permissions",
                f'Key (role_id)=({role.id}) is not present in table "roles".',
            )),
        ))
        try:
            with pytest.raises(RoleNotFoundError) as refusal:
                repo.save(role)
        finally:
            session.flush = original
            session.rollback()

        assert refusal.value.role_name == "association-orphaned"

    def test_a_taken_name_is_still_a_taken_name(self, store):
        """
        The measurement the catch was written for, unchanged: SQLite
        names the column in the message and reports no diagnostics, so
        this is also the path every other engine's fallback takes.
        """
        repo, session = store
        a_role(store, "taken-name")

        with pytest.raises(RoleAlreadyExistsError):
            repo.save(
                Role(id=str(uuid.uuid4()), name="taken-name", description="x")
            )
        session.rollback()

    def test_a_violation_from_somewhere_else_is_re_raised(self, store):
        repo, session = store
        role = a_role(store, "violated-elsewhere")

        original = flushing_raises(session, IntegrityError(
            "INSERT INTO something_else", {},
            Refusal(Diagnostics(
                "something_else",
                f'Key (role_id)=({role.id}) is not present in table "roles".',
            )),
        ))
        try:
            with pytest.raises(IntegrityError):
                repo.save(role)
        finally:
            session.flush = original
            session.rollback()
