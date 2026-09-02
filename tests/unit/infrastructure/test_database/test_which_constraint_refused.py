"""
Tests that only the address index is read as "that address is taken".

``SQLAlchemyUserRepository.save`` flushes the account and the role
associations together, and it used to answer every ``IntegrityError`` that
flush could raise with ``EmailAlreadyRegisteredError``. Measured on the
running stack: ``PUT /api/v1/admin/users/<id>/roles`` naming one role
twice came back `409 EMAIL_ALREADY_REGISTERED`, "Email already
registered", for a request carrying no address at all.

The distinction is asked of the two databases in the two forms they give
it, both taken from them rather than imagined:

    PostgreSQL 15  duplicate key value violates unique constraint
                   "ix_users_email"          -> diag.constraint_name
                   duplicate key value violates unique constraint
                   "user_roles_pkey"         -> diag.constraint_name
    SQLite         UNIQUE constraint failed: users.email
                   (no diagnostics at all)

Checked here rather than through a route because SQLite does not refuse
the duplicate association in the first place, so the situation the
narrowing is about cannot be reached from the suite's own database.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from link_shortener.infrastructure.database.repositories.sqlalchemy_user_repository import (
    EMAIL_INDEX_NAME, _is_email_clash,
)


class Diagnostics:
    """What psycopg puts on an error: the constraint that refused."""

    def __init__(self, constraint_name):
        self.constraint_name = constraint_name


class PostgresError(Exception):
    """A driver error carrying diagnostics, as psycopg raises."""

    def __init__(self, message, constraint_name):
        super().__init__(message)
        self.diag = Diagnostics(constraint_name)


def postgres(constraint_name):
    """An integrity error as PostgreSQL raises it."""
    return IntegrityError(
        "INSERT INTO ...",
        {},
        PostgresError(
            f'duplicate key value violates unique constraint '
            f'"{constraint_name}"',
            constraint_name,
        ),
    )


def sqlite(message):
    """An integrity error as SQLite raises it: a message and nothing else."""
    return IntegrityError("INSERT INTO ...", {}, Exception(message))


class TestTheAddressIndex:

    def test_the_name_is_the_one_the_model_carries(self):
        """
        Read off the model rather than written out, so the string this
        compares against cannot drift from the index the database has.
        """
        assert EMAIL_INDEX_NAME == "ix_users_email"

    def test_postgres_naming_that_index_is_the_address(self):
        assert _is_email_clash(postgres(EMAIL_INDEX_NAME))

    def test_sqlite_naming_that_column_is_the_address(self):
        assert _is_email_clash(sqlite("UNIQUE constraint failed: users.email"))


class TestEverythingElse:

    @pytest.mark.parametrize("constraint", [
        "user_roles_pkey",
        "users_pkey",
        "refresh_sessions_pkey",
        "ix_roles_name",
    ])
    def test_another_constraint_is_not_the_address(self, constraint):
        """
        The one that reached the running stack was ``user_roles_pkey``,
        raised by a role named twice in one request.
        """
        assert not _is_email_clash(postgres(constraint))

    @pytest.mark.parametrize("message", [
        "UNIQUE constraint failed: user_roles.user_id, user_roles.role_id",
        "UNIQUE constraint failed: roles.name",
        "FOREIGN KEY constraint failed",
    ])
    def test_another_message_is_not_the_address(self, message):
        assert not _is_email_clash(sqlite(message))
