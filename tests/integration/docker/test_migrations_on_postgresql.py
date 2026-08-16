"""The baseline migration, run against the backend it is deployed on.

``tests/integration/infrastructure/database/test_migrations.py`` builds the
schema from nothing and checks what came out -- against SQLite, because that
is what a clone gets out of the box. Its own docstring says the rest:
"PostgreSQL-only behaviour belongs in ``tests/integration/docker/``". There
was nothing there, and this is what that cost.

``link_visits.is_bot`` was declared ``server_default=sa.text('0')``. SQLite
takes the integer for a boolean and the whole suite stayed green; PostgreSQL
refuses it outright -- *column "is_bot" is of type boolean but default
expression is of type integer* -- and since Alembic runs a revision in one
transaction, the failure left a deployed database with **no schema at all**.
Measured by bringing the stack up on empty volumes: the migration container
exited 1, and the application came up against nine tables that were never
created.

Everything else here runs against a schema built by ``create_all`` from the
models, which executes no revision and so cannot see the difference between
a model and the migration that is supposed to reproduce it.

The migration is run into a database of its own, made and dropped by this
file: the shared one already carries tables from every other test in this
directory, and a revision applied on top of them would prove nothing.
"""

import pytest
from sqlalchemy import create_engine, text

from link_shortener.infrastructure.cli.commands.alembic import AlembicCommands
from tests.support.real_stack import POSTGRES_URL


SCRATCH = "migration_check"
"""Name of the database this file builds. Dropped afterwards, and dropped
before, so that a previous run killed part-way does not stop this one."""


TABLES_THE_APPLICATION_NEEDS = {
    "urls", "users", "roles", "permissions", "role_permissions",
    "user_roles", "refresh_sessions", "email_verifications",
    "link_visits", "link_visit_days",
}
"""What a deployment has to find after ``alembic upgrade head``.

``link_visits`` and ``link_visit_days`` are named for the reason this file
exists: they are the two the broken default kept out of a real database,
and the two nothing else here would have missed.
"""


def server(url=POSTGRES_URL):
    """
    A connection to the server rather than to one database on it.

    ``CREATE DATABASE`` cannot run inside a transaction, and it cannot run
    from inside the database being created or dropped, so this points at
    ``postgres`` and commits as it goes.

    Args:
        url: The stack's URL, whose database name is replaced.

    Returns:
        An engine in autocommit.
    """
    return create_engine(
        url.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT"
    )


@pytest.fixture(scope="module", autouse=True)
def the_shared_schema_this_directory_cleans(app):
    """
    Build the tables the directory's own cleaner truncates after each test.

    Nothing here touches the shared database -- the revision is run into
    one of its own -- but ``conftest.py`` truncates the shared one after
    every test in this directory, and the tables it names are created by
    the session-scoped ``app`` fixture. Without this, the file passes in
    the company of its neighbours and errors in teardown when run alone,
    which is the worst of the two orders to be wrong in.

    Args:
        app: The directory's application fixture, requested for its
            schema and nothing else.
    """


@pytest.fixture(scope="module")
def migrated_database():
    """
    An empty database with ``alembic upgrade head`` run into it.

    Returns:
        Tuple of the URL and the output of the upgrade.
    """
    url = POSTGRES_URL.rsplit("/", 1)[0] + f"/{SCRATCH}"

    engine = server()
    with engine.connect() as connection:
        connection.execute(text(f"DROP DATABASE IF EXISTS {SCRATCH}"))
        connection.execute(text(f"CREATE DATABASE {SCRATCH}"))
    engine.dispose()

    ok, output = AlembicCommands.upgrade("head", database_url=url)

    yield url, ok, output

    engine = server()
    with engine.connect() as connection:
        # Whatever still holds it: a failed upgrade can leave a connection
        # behind, and DROP DATABASE refuses while one is open.
        connection.execute(text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{SCRATCH}'"
        ))
        connection.execute(text(f"DROP DATABASE IF EXISTS {SCRATCH}"))
    engine.dispose()


def tables_in(url):
    """
    The tables a database has.

    Args:
        url: Connection URL.

    Returns:
        Set of table names in the public schema.
    """
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            return {
                row[0]
                for row in connection.execute(text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                ))
            }
    finally:
        engine.dispose()


class TestTheRevisionRunsOnPostgreSQL:

    def test_the_upgrade_succeeds(self, migrated_database):
        _url, ok, output = migrated_database

        assert ok, output

    def test_every_table_the_application_needs_is_there(self, migrated_database):
        """
        An upgrade that reported success and built half a schema is the
        shape this failure took: the exception arrived at the last table
        and took the nine before it down with it.
        """
        url, _ok, _output = migrated_database

        assert TABLES_THE_APPLICATION_NEEDS <= tables_in(url)

    def test_a_visit_can_actually_be_written(self, migrated_database):
        """
        Building the column is not the same as being able to use it.

        The default is what broke, so a row that names neither ``is_bot``
        nor its neighbours is what proves it usable -- and it is what the
        worker inserts on every redirect.
        """
        url, _ok, _output = migrated_database

        engine = create_engine(url)
        try:
            with engine.begin() as connection:
                # Only the columns the revision declares NOT NULL without a
                # default: everything else is what the schema is being asked
                # to supply.
                connection.execute(text(
                    "INSERT INTO urls (id, url_hash, original_url, short_code, "
                    "clicks) VALUES ('u1', 'hash', 'https://example.com', "
                    "'abc1234', 0)"
                ))
                connection.execute(text(
                    "INSERT INTO link_visits (id, link_id, occurred_at) "
                    "VALUES ('v1', 'u1', CURRENT_TIMESTAMP)"
                ))

            with engine.connect() as connection:
                written = connection.execute(text(
                    "SELECT is_bot, device, browser FROM link_visits WHERE id = 'v1'"
                )).one()
        finally:
            engine.dispose()

        assert written == (False, "unknown", "unknown")
