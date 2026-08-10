"""The schema a migration builds and the one the models build must agree.

The suite runs on ``create_all`` from the ORM models, because
``TestingConfig`` sets ``USE_ALEMBIC = False``. A deployment runs
``alembic upgrade head``. Nothing connects the two: a column added to a
model and forgotten in a revision passes every test here and is missing in
production, and a column widened in a revision and not in the model is
silently narrower on the SQLite that developers run.

This compares the two against each other rather than either against a
literal, which is the only comparison that can fail for the right reason.
It covers the tables the confirmation work touches; the older tables are
covered by the fact that they were built together.
"""

import sqlite3

import pytest
from sqlalchemy import create_engine

from link_shortener.infrastructure.cli.commands.alembic import AlembicCommands
from link_shortener.infrastructure.database.models.base import Base
# Imported for their side effect: a model registers itself with the
# metadata when its module is imported, and create_all builds only what
# the metadata knows about.
from link_shortener.infrastructure.database.repositories import (  # noqa: F401
    sqlalchemy_email_verification_repository,
    sqlalchemy_link_repository,
    sqlalchemy_permission_repository,
    sqlalchemy_refresh_session_repository,
    sqlalchemy_role_repository,
    sqlalchemy_user_repository,
)


COMPARED_TABLES = ["users", "email_verifications"]


def columns(path, table):
    """Read a table's columns straight out of SQLite.

    Args:
        path: Path to the SQLite file.
        table: Table to inspect.

    Returns:
        Dict of column name to (declared type, not-null flag, default).

    The default is part of the comparison and was not, which cost a real
    hole: a model declaring ``server_default=true()`` against a revision
    declaring ``false()`` matched on type and nullability, and every row
    inserted without naming the column would have been confirmed on the
    suite's database and unconfirmed on a deployment's.
    """
    connection = sqlite3.connect(path)
    try:
        return {
            row[1]: (row[2].upper(), bool(row[3]), row[4])
            for row in connection.execute(f"PRAGMA table_info({table})")
        }
    finally:
        connection.close()


def indexes(path, table):
    """Read a table's indexes, by the columns they cover.

    Named indexes are compared by their columns rather than their names,
    because the two builders name them differently and the name is not
    what makes a lookup fast or a value unique.

    Args:
        path: Path to the SQLite file.
        table: Table to inspect.

    Returns:
        Set of (columns tuple, unique flag).
    """
    connection = sqlite3.connect(path)
    try:
        found = set()
        for row in connection.execute(f"PRAGMA index_list({table})"):
            name, unique = row[1], bool(row[2])
            covered = tuple(
                info[2] for info in connection.execute(f"PRAGMA index_info({name})")
            )
            found.add((covered, unique))
        return found
    finally:
        connection.close()


@pytest.fixture
def migrated(tmp_path):
    """A database built by running every revision."""
    path = tmp_path / "migrated.db"
    ok, output = AlembicCommands.upgrade("head", database_url=f"sqlite:///{path}")
    assert ok, f"migrations did not reach head: {output}"
    return path


@pytest.fixture
def created(tmp_path):
    """A database built by ``create_all`` from the ORM models."""
    path = tmp_path / "created.db"
    engine = create_engine(f"sqlite:///{path}")
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()
    return path


class TestTheTwoBuildersAgree:
    """What a deployment gets and what the suite runs on."""

    @pytest.mark.parametrize("table", COMPARED_TABLES)
    def test_the_columns_match(self, migrated, created, table):
        assert columns(migrated, table) == columns(created, table)

    @pytest.mark.parametrize("table", COMPARED_TABLES)
    def test_the_indexes_match(self, migrated, created, table):
        assert indexes(migrated, table) == indexes(created, table)


class TestWhatTheMigrationDecided:
    """A choice in the baseline that no schema comparison can see."""

    @pytest.mark.parametrize("builder", ["migrated", "created"])
    def test_a_row_inserted_without_the_column_is_unconfirmed(
        self, request, builder
    ):
        """The server default is the backstop for anything that writes to
        this table without knowing about confirmation -- a repair script, a
        fixture, a later migration. Trusting by default there would hand
        out confirmed accounts nobody confirmed.

        Both builders are asked, because they declare the default
        separately: the baseline writes ``sa.false()`` and the model writes
        ``false()``, and only one of them was ever checked.
        """
        database = request.getfixturevalue(builder)
        connection = sqlite3.connect(database)
        try:
            connection.execute(
                "INSERT INTO users (id, email, password_hash, is_active, "
                "created_at) VALUES ('fresh', 'fresh@example.com', 'hash', 1, "
                "'2026-08-10 00:00:00')"
            )
            connection.commit()
            verified = connection.execute(
                "SELECT email_verified FROM users WHERE id = 'fresh'"
            ).fetchone()[0]
        finally:
            connection.close()

        assert verified == 0
