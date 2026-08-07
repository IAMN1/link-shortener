"""
Unit tests for the connection deadlines on ``DatabaseManager``.

Without them the wait for an unreachable PostgreSQL is the operating
system's TCP timeout, measured in minutes, against a container probe that
gives up after ten seconds.
"""

from unittest.mock import MagicMock, patch

from link_shortener.infrastructure.database.manager import DatabaseManager


POSTGRES_URL = "postgresql+psycopg://user:pass@db:5432/shortener"


def _created_engines(manager_action):
    """
    Run an action with ``create_engine`` stubbed and collect its calls.

    ``event.listens_for`` is stubbed alongside it: the manager registers a
    connect-time listener for SQLite, and a listener cannot be attached to
    a mock engine. What this helper is for is the arguments the engine was
    built with, and the two are unrelated.

    Args:
        manager_action: Callable driving the manager under test.

    Returns:
        The list of ``create_engine`` call objects.
    """
    with patch(
        "link_shortener.infrastructure.database.manager.create_engine"
    ) as create, patch(
        "link_shortener.infrastructure.database.manager.event.listens_for"
    ):
        manager_action()
        return create.call_args_list


class TestConnectTimeout:
    """A connection attempt has to have a deadline of its own."""

    def test_postgresql_connections_carry_a_deadline(self):
        manager = DatabaseManager(
            POSTGRES_URL, echo=False, database_type="postgresql", connect_timeout=3
        )

        calls = _created_engines(manager.connect)

        assert calls[0].kwargs["connect_args"] == {"connect_timeout": 3}

    def test_the_probe_connection_carries_the_same_deadline(self):
        # The probe is the one the container healthcheck waits on, so it is
        # the one that must not be able to hang.
        manager = DatabaseManager(
            POSTGRES_URL, echo=False, database_type="postgresql", connect_timeout=3
        )
        manager.connect()

        calls = _created_engines(lambda: manager.probe())

        assert calls[0].kwargs["connect_args"] == {"connect_timeout": 3}

    def test_sqlite_gets_no_connection_arguments(self):
        # SQLite has no server to connect to and rejects the argument. It
        # does get a connect-time listener, for the foreign-key pragma --
        # see TestSqliteForeignKeys.
        manager = DatabaseManager(
            "sqlite:///:memory:", echo=False, database_type="sqlite",
            connect_timeout=3,
        )

        calls = _created_engines(manager.connect)

        assert "connect_args" not in calls[0].kwargs


class TestQueryDeadlines:
    """
    A connection deadline is not enough: it only covers getting connected.

    A query the server is running but not finishing, and a peer that went
    away mid-query, are separate waits and each needs its own bound.
    """

    def test_a_statement_cannot_run_forever(self):
        manager = DatabaseManager(
            POSTGRES_URL, echo=False, database_type="postgresql",
            connect_timeout=3, statement_timeout=10,
        )

        calls = _created_engines(manager.connect)

        assert calls[0].kwargs["connect_args"]["options"] == (
            "-c statement_timeout=10000"
        )

    def test_a_silent_peer_is_given_up_on(self):
        # Otherwise a worker blocks on a socket that will never answer.
        manager = DatabaseManager(
            POSTGRES_URL, echo=False, database_type="postgresql",
            connect_timeout=3, statement_timeout=10,
        )

        args = _created_engines(manager.connect)[0].kwargs["connect_args"]

        assert args["keepalives"] == 1
        assert args["keepalives_idle"] > 0
        assert args["keepalives_interval"] > 0
        assert args["keepalives_count"] > 0

    def test_the_probe_carries_the_deadlines_too(self):
        manager = DatabaseManager(
            POSTGRES_URL, echo=False, database_type="postgresql",
            connect_timeout=3, statement_timeout=10,
        )
        manager.connect()

        args = _created_engines(lambda: manager.probe())[0].kwargs["connect_args"]

        assert args["options"] == "-c statement_timeout=10000"

    def test_sqlite_is_left_alone(self):
        manager = DatabaseManager(
            "sqlite:///:memory:", echo=False, database_type="sqlite",
            connect_timeout=3, statement_timeout=10,
        )

        calls = _created_engines(manager.connect)

        assert "connect_args" not in calls[0].kwargs


class TestProbeIsolation:
    """The probe must not draw on the pool it is meant to report about."""

    def test_the_probe_engine_holds_no_connections_between_calls(self):
        from sqlalchemy.pool import NullPool

        manager = DatabaseManager(
            POSTGRES_URL, echo=False, database_type="postgresql", connect_timeout=3
        )
        manager.connect()

        calls = _created_engines(lambda: manager.probe())

        # A probe running every few seconds must not become a leak itself.
        assert calls[0].kwargs["poolclass"] is NullPool

    def test_the_probe_does_not_use_the_shared_engine(self):
        manager = DatabaseManager(
            POSTGRES_URL, echo=False, database_type="postgresql", connect_timeout=3
        )
        with patch(
            "link_shortener.infrastructure.database.manager.create_engine"
        ) as create:
            create.side_effect = [MagicMock(), MagicMock()]
            manager.connect()
            shared = manager.engine
            manager.probe()

        # Borrowing from the shared pool reports a busy service as a dead
        # database, after first waiting out the pool timeout.
        assert manager._probe_engine is not shared
        assert create.call_count == 2


class TestSqliteForeignKeys:
    """
    SQLite parses ``REFERENCES`` and then ignores it.

    Enforcement is off unless every connection asks for it, and the pragma
    is per-connection, so it has to be set on connect. Off, an
    ``ON DELETE`` clause is decoration: the cascade behind ``urls.owner_id``
    did not happen, and a row could name an account that does not exist --
    which PostgreSQL would have refused, so the test suite was accepting
    data production could not hold.
    """

    def test_a_connection_enforces_foreign_keys(self):
        from sqlalchemy import text

        manager = DatabaseManager(
            "sqlite:///:memory:", echo=False, database_type="sqlite"
        ).connect()

        with manager.engine.connect() as connection:
            assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1

    def test_postgres_is_not_given_the_pragma(self):
        """It has always enforced them; the pragma is not its dialect."""
        with patch(
            "link_shortener.infrastructure.database.manager.event.listens_for"
        ) as listens_for:
            DatabaseManager(
                POSTGRES_URL, echo=False, database_type="postgresql"
            ).connect()

        listens_for.assert_not_called()
