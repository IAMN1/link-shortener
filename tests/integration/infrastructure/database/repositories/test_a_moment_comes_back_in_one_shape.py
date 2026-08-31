"""What shape a stored moment has when it reaches a caller.

Every timestamp column is declared ``DateTime(timezone=True)``, which
PostgreSQL honours and SQLite does not: SQLite has no offset to store, so
everything read back from it is naive. The link repository restores the
zone as it builds the entity -- three fields, with a comment saying why --
and that restoration is what makes `POST /api/v1/shorten` answer
``...+00:00``.

The account repository handed ``model.created_at`` straight through.
Measured on the documented local setup, which is SQLite: an account's
``created_at`` reached the wire as ``2026-08-30T17:10:09.606313`` while a
link made in the same second reached it as ``...+00:00`` -- one API
answering in two shapes, from one deployment, for the same kind of value.
``UserResponseSchema.serialize_datetime`` says it is handed "a
timezone-aware datetime or ``None``"; it was not.

Held as a property over the repository rather than as one assertion about
one field, because the fault is a field somebody forgot rather than a
field that is wrong.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from link_shortener.infrastructure.database.models.user_model import (
    UserModel,
)
from link_shortener.infrastructure.database.unit_of_work import (
    SQLAlchemyUnitOfWork,
)


HASH = "$2b$12$" + "x" * 53


@pytest.fixture()
def account(app, request):
    """
    One account, written the way the application writes accounts.

    Through the ORM, and that is the whole fixture: a row inserted with
    raw SQL and a bound aware datetime is stored by the driver as an ISO
    string *carrying* the offset, and reads back aware whatever the
    repository does. Written that way this file passed with the defect
    in place -- it was measuring its own INSERT.
    """
    moment = datetime.now(timezone.utc)
    user_id = f"tz-{request.node.name[:40]}"
    with app.app_context():
        with app.container.get_db_manager().session() as session:
            session.add(UserModel(
                id=user_id,
                email=f"{user_id}@example.test",
                password_hash=HASH,
                is_active=True,
                email_verified=True,
                created_at=moment,
                last_login=moment,
            ))
    return user_id


class TestAnAccountsMomentsCarryTheirZone:

    def test_every_moment_read_back_is_aware(self, app, account):
        """
        The property, over whatever datetime fields the entity carries:
        a fifth one added later is covered without editing this file.
        """
        with app.app_context():
            uow = SQLAlchemyUnitOfWork(app.container.get_db_manager())
            with uow:
                user = uow.users.find_by_id(account)

        moments = {
            name: value for name, value in vars(user).items()
            if isinstance(value, datetime)
        }

        assert moments, "the account carries no moments to check"
        naive = [name for name, value in moments.items() if value.tzinfo is None]
        assert not naive, f"these came back without a zone: {naive}"

    def test_the_instant_itself_is_unchanged(self, app, account):
        """
        Restoring a zone must not move the moment: the values written are
        UTC, so marking them UTC is a restoration, and a shift would make
        every account look an offset old.
        """
        with app.app_context():
            manager = app.container.get_db_manager()
            with manager.session() as session:
                stored = session.execute(
                    text("SELECT created_at FROM users WHERE id = :id"),
                    {"id": account},
                ).scalar()

            uow = SQLAlchemyUnitOfWork(manager)
            with uow:
                user = uow.users.find_by_id(account)

        assert user.created_at.replace(tzinfo=None) == (
            stored.replace(tzinfo=None) if isinstance(stored, datetime)
            else datetime.fromisoformat(str(stored)).replace(tzinfo=None)
        )

    def test_an_absent_moment_stays_absent(self, app, request):
        """
        ``last_login`` is null until the account signs in, and a zone
        cannot be given to nothing.
        """
        user_id = f"tz-null-{request.node.name[:30]}"
        with app.app_context():
            manager = app.container.get_db_manager()
            with manager.session() as session:
                session.add(UserModel(
                    id=user_id,
                    email=f"{user_id}@example.test",
                    password_hash=HASH,
                    is_active=True,
                    email_verified=True,
                    created_at=datetime.now(timezone.utc),
                ))

            uow = SQLAlchemyUnitOfWork(manager)
            with uow:
                user = uow.users.find_by_id(user_id)

        assert user.last_login is None
