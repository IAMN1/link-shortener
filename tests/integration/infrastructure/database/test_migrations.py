"""The baseline migration has to actually build a database.

Nothing exercised this before, and it was broken: the chain this baseline
replaced dropped a foreign key by the name PostgreSQL invents for it, while
the revision that created the key left it unnamed. On SQLite -- the default
of the documented local setup -- there was no such name, so a fresh database
stopped part-way and could not be built by migrations at all. It went
unnoticed because every other test builds the schema with ``create_all``
from the models, which never runs a revision.

Step A3 of the quick start is ``alembic upgrade head``, so this is the path
a clone takes on its first run. Tested against SQLite because that is what a
developer gets out of the box; PostgreSQL-only behaviour belongs in
``tests/integration/docker/``.
"""

import sqlite3

import pytest

from link_shortener.infrastructure.cli.commands.alembic import AlembicCommands


# Column order of PRAGMA foreign_key_list.
ON_DELETE = 6


@pytest.fixture
def database(tmp_path):
    """Path and URL of a database file that does not exist yet."""
    path = tmp_path / "migrated.db"
    return path, f"sqlite:///{path}"


def tables(path):
    """Return the table names the database currently has.

    Args:
        path: Path to the SQLite file.

    Returns:
        Set of table names.
    """
    connection = sqlite3.connect(path)
    try:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        connection.close()


def foreign_keys(path, table):
    """Return the foreign keys a table declares.

    Args:
        path: Path to the SQLite file.
        table: Table to inspect.

    Returns:
        List of PRAGMA rows.
    """
    connection = sqlite3.connect(path)
    try:
        return list(connection.execute(f"PRAGMA foreign_key_list({table})"))
    finally:
        connection.close()


class TestMigrationChain:
    """From nothing to head, and back."""

    def test_a_fresh_database_reaches_head(self, database):
        """The whole point: an empty file becomes a usable schema."""
        path, url = database

        ok, output = AlembicCommands.upgrade("head", database_url=url)
        assert ok, output

        ok, current = AlembicCommands.status(database_url=url)
        assert ok, current
        assert "0001" in current

    def test_the_expected_tables_exist_afterwards(self, database):
        """A migration that runs but builds nothing would still "pass"."""
        path, url = database
        ok, output = AlembicCommands.upgrade("head", database_url=url)
        assert ok, output

        assert {
            "urls", "users", "roles", "permissions",
            "role_permissions", "user_roles", "refresh_sessions",
        } <= tables(path)

    def test_links_are_left_pointing_at_their_owner_s_deletion(self, database):
        """The cascade is a decision about data, not a detail of the schema.

        Links do not outlive the account that made them, and there is no
        recovery. Asserted against the built database rather than against
        the revision's source, because the two have disagreed: the code that
        set this up reported success on PostgreSQL while failing outright on
        SQLite, and only the schema itself tells them apart.
        """
        path, url = database
        ok, output = AlembicCommands.upgrade("head", database_url=url)
        assert ok, output

        keys = foreign_keys(path, "urls")

        owner_keys = [k for k in keys if k[3] == "owner_id"]
        assert owner_keys, f"no foreign key on owner_id: {keys}"
        assert owner_keys[0][ON_DELETE] == "CASCADE"

    def test_the_baseline_can_be_undone_and_redone(self, database):
        """A downgrade nobody runs is a downgrade nobody knows is broken."""
        path, url = database
        ok, output = AlembicCommands.upgrade("head", database_url=url)
        assert ok, output

        ok, output = AlembicCommands.downgrade("base", database_url=url)
        assert ok, output
        assert tables(path) == {"alembic_version"}

        ok, output = AlembicCommands.upgrade("head", database_url=url)
        assert ok, output
        assert "urls" in tables(path)
        assert foreign_keys(path, "urls")[0][ON_DELETE] == "CASCADE"

    def test_migrations_land_in_the_database_they_were_given(self, database):
        """The handoff decides the target, not the ambient environment.

        Alembic runs in a subprocess and would otherwise rebuild its own
        configuration from whatever happens to be exported.
        """
        path, url = database
        ok, output = AlembicCommands.upgrade("head", database_url=url)
        assert ok, output

        assert path.exists()
        assert path.stat().st_size > 0
