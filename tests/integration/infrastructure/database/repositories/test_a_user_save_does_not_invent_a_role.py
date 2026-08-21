"""Saving a user is not how a role comes into existence.

``_sync_roles`` matched the user's roles by name and, finding none,
created the row itself -- ``is_system=False`` and no permissions at all.
That is a write into the roles table from the user repository, and it is
reachable without anything exotic: two administrators, one deleting a role
between the other's lookup and save. The role came back stripped of
everything it granted and of the flag protecting it, and nothing said so.
"""

import pytest

from link_shortener.domain import (
    Email, PasswordHash, Permission, Role, RoleNotFoundError, User
)
from link_shortener.infrastructure.database.models.role_model import RoleModel
from link_shortener.infrastructure.database.repositories.sqlalchemy_user_repository import (
    SQLAlchemyUserRepository,
)


# A hash of the right shape; nothing here checks a password.
HASH = "$2b$12$" + "a" * 53


@pytest.fixture()
def store(app):
    """A user repository and the session behind it."""
    with app.app_context():
        db_manager = app.container.get_db_manager()
        with db_manager.session() as session:
            yield SQLAlchemyUserRepository(session), session


def _user(email, roles):
    """Build a domain user carrying exactly these roles."""
    return User.create(
        email=Email(email),
        password_hash=PasswordHash(HASH),
        roles=roles,
    )


class TestARoleTheDatabaseDoesNotHave:
    """A user carrying a role no row answers to is refused, not obliged."""

    def test_saving_refuses_rather_than_creating_the_role(self, store):
        repository, session = store
        vanished = Role(
            id="invent-role-vanished",
            name="invent-vanished",
            is_system=True,
            permissions=(
                Permission("invent-p", "admin:all", "admin", "all"),
            ),
        )

        with pytest.raises(RoleNotFoundError) as refusal:
            repository.save(_user("invent-role@example.test", [vanished]))

        assert refusal.value.role_name == "invent-vanished"
        session.rollback()
        assert session.get(RoleModel, "invent-role-vanished") is None, (
            "saving a user wrote a row into the roles table"
        )

    def test_a_role_that_is_there_is_bound_by_its_id(self, store):
        """The account binds to the row, not to whatever wears the name."""
        repository, session = store
        session.add(RoleModel(
            id="invent-role-real", name="invent-real", is_system=True
        ))
        session.flush()

        saved = repository.save(_user(
            "invent-role-ok@example.test",
            [Role(id="invent-role-real", name="invent-real")],
        ))
        session.flush()

        stored = repository.find_by_id(saved.id)
        assert [role.id for role in stored.roles] == ["invent-role-real"]
