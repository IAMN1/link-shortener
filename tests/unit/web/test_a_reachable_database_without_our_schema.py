"""
``/health`` on a database that answers and holds none of our tables.

This is the state the project measured itself reporting as ``healthy``.
Walking the README's Docker column on a fresh clone brought up PostgreSQL
and two Redis, and left the application on SQLite: the migration container
wrote a schema into its own filesystem by a relative path and exited 0, the
application opened an empty file beside it, and then

    GET /health  ->  200  {"status": "healthy", "database": "ok"}
    GET /        ->  500  OperationalError: no such table: roles

Every network measure of that database was correct. It was reachable, it
answered ``SELECT 1``, its container was healthy -- and the service behind
it served nothing at all. An orchestrator asking "should I keep sending
traffic here?" was told yes.

``docs/decisions.md`` already carried the finding for the deployed
profiles, where the refusal is to start on SQLite at all. Under
``development`` -- which is what the Docker template selects -- nothing
refused, so the guard had to be in the answer rather than in the start-up.

What these hold: that the endpoint tells the three database states apart,
and that only the two which serve nothing are 503.
"""

import pytest


@pytest.fixture
def schema_is(app):
    """Make the health check report a whole or a broken schema.

    Reaches into the container's checker the way the other tests in this
    package do. The checker is real; only its answer is stubbed, so the
    rendering under test is the real rendering.
    """
    def answering(whole: bool):
        app.container.health_check.check_schema = lambda: whole
        return whole

    return answering


class TestTheThreeDatabaseStatesAreToldApart:

    def test_a_whole_schema_reads_ok(self, client, schema_is):
        schema_is(True)

        body = client.get("/health").get_json()

        assert body["components"]["database"] == "ok"

    def test_a_missing_schema_reads_no_schema(self, client, schema_is):
        schema_is(False)

        body = client.get("/health").get_json()

        # Not "unavailable": that word sends an operator to look at
        # connectivity, which is the one thing that is fine here.
        assert body["components"]["database"] == "no_schema"

    def test_an_unreachable_database_still_reads_unavailable(
        self, client, app, schema_is
    ):
        # The schema answer is False here too -- a database that cannot be
        # reached cannot be inspected -- and the row must still say the
        # thing that is actually wrong.
        schema_is(False)
        app.container.health_check.check_database = lambda: False

        body = client.get("/health").get_json()

        assert body["components"]["database"] == "unavailable"

    def test_a_database_that_ran_out_of_the_budget_still_reads_timeout(
        self, client, app, schema_is
    ):
        # The state that must not be swallowed by the schema branch. A
        # dependency that ran out of the check's budget and one that
        # answered no are both unusable, and only the first says which
        # dependency is hanging -- the row has said so since before the
        # schema was asked about, and splitting the database's rendering
        # out of `describe` had to keep it.
        import time

        schema_is(True)
        app.container.health_check.timeout = 0.01
        app.container.health_check.check_database = lambda: time.sleep(0.5) or True

        body = client.get("/health").get_json()

        assert body["components"]["database"] == "timeout"


class TestTheVerdictAndTheCode:

    def test_a_missing_schema_is_not_healthy(self, client, schema_is):
        schema_is(False)

        assert client.get("/health").get_json()["status"] == "unhealthy"

    def test_a_missing_schema_answers_503(self, client, schema_is):
        # The code answers the orchestrator's question. A restart does not
        # fix a migration that never ran -- and neither does it fix a
        # database that is down, which has answered 503 all along. What
        # 503 does is take the instance out of a load balancer's rotation,
        # and an instance that answers 500 to every request belongs out of
        # it.
        schema_is(False)

        assert client.get("/health").status_code == 503

    def test_a_whole_schema_answers_200(self, client, schema_is):
        schema_is(True)

        assert client.get("/health").status_code == 200

    def test_a_failed_cache_is_still_only_degraded(self, client, app, schema_is):
        # The rule this addition had to not break: a cache or a broker
        # that is down is worth reporting and not worth a restart, and the
        # schema is counted with the database rather than with them.
        schema_is(True)
        app.container.health_check.is_cache_configured = lambda: True
        app.container.health_check.check_cache = lambda: False

        response = client.get("/health")

        assert response.status_code == 200
        assert response.get_json()["status"] == "degraded"
