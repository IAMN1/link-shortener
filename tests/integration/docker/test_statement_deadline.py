"""
The statement deadline against a real PostgreSQL.

``tests/unit/infrastructure/test_database/test_manager_timeouts.py`` checks
that ``DatabaseManager`` *passes* the deadline to ``create_engine`` -- with
``create_engine`` itself stubbed out. That is worth checking and it is not
the same thing as the deadline working: if the value were passed and then
ignored, those tests stay green. They did, in fact, sit green alongside a
request that hung for 150 seconds against a frozen database.

So this one asks the server. A query that sleeps past the limit has to come
back as an error rather than as a wait, and one that finishes inside it has
to be left alone.
"""

import time

import pytest
from sqlalchemy import text

from link_shortener.infrastructure.database.manager import DatabaseManager

from tests.integration.docker.conftest import POSTGRES_URL


STATEMENT_TIMEOUT = 2


@pytest.fixture()
def manager(app):
    """
    A manager with a short, real deadline.

    Depends on ``app`` only for the schema: the autouse cleanup in this
    package truncates the tables after every test, and without something
    having created them it fails on a suite that otherwise passed. Nothing
    here reads a table.
    """
    manager = DatabaseManager(
        POSTGRES_URL,
        echo=False,
        database_type="postgresql",
        connect_timeout=3,
        statement_timeout=STATEMENT_TIMEOUT,
    )
    manager.connect()
    yield manager
    manager.close()


class TestTheDeadlineIsEnforcedByTheServer:
    """Configured is not the same as effective."""

    def test_the_session_reports_the_limit(self, manager):
        with manager.session() as session:
            setting = session.execute(text("SHOW statement_timeout")).scalar()

        assert setting == f"{STATEMENT_TIMEOUT}s"

    def test_a_query_past_the_limit_is_aborted(self, manager):
        started = time.perf_counter()

        with pytest.raises(Exception) as refused:
            with manager.session() as session:
                session.execute(text("SELECT pg_sleep(30)"))

        elapsed = time.perf_counter() - started
        # Aborted near the limit, not after the sleep and not after the
        # operating system's TCP timeout.
        assert elapsed < STATEMENT_TIMEOUT + 3, f"waited {elapsed:.1f}s"
        assert "timeout" in str(refused.value).lower()

    def test_a_query_inside_the_limit_is_left_alone(self, manager):
        with manager.session() as session:
            result = session.execute(text("SELECT pg_sleep(0.1), 42")).first()

        assert result[1] == 42
