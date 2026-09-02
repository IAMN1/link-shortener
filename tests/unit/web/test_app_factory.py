from unittest.mock import MagicMock, Mock, patch
from link_shortener.web.app_factory import create_app, _seed_base_roles_if_ready


class Test_app_factory:
    """Tests for the app_factory"""

    def test_create_app_with_config(self, test_config):
        """App factory accepts custom config object."""

        # Act
        app = create_app(test_config)

        # Assert
        assert app is not None
        assert app.config["TESTING"] is True
        assert app.config["DEBUG"] is False

    def test_health_endpoint(self, client):
        """GET /health returns 200 and reports each dependency."""

        # Act
        response = client.get("/health")

        # Assert
        assert response.status_code == 200
        body = response.get_json()
        assert body["status"] == "healthy"
        # A bare "healthy" told the container nothing: it stayed green with
        # the database on the floor.
        assert set(body["components"]) == {
            "database", "cache", "task_queue", "rate_limiter"
        }

    def test_health_endpoint_reports_degradation_without_demanding_a_restart(
        self, app, client
    ):
        """A failed cache is worth reporting, but not worth a restart."""
        # A deployment that asked for Redis and lost it -- not one that runs
        # without a cache on purpose, which is the test app's default.
        app.container.health_check.is_cache_configured = lambda: True
        app.container.health_check.check_cache = lambda: False

        response = client.get("/health")

        # The container asks "should I restart this?" -- and restarting does
        # not fix Redis while it does take down a service that still works.
        assert response.status_code == 200
        body = response.get_json()
        # ...but "healthy" would leave the operator with nothing to see.
        assert body["status"] == "degraded"
        assert body["components"]["cache"] == "unavailable"

    def test_health_endpoint_reports_a_dead_database(self, app, client):
        """A container must not stay green with the database on the floor."""
        app.container.health_check.check_database = lambda: False

        response = client.get("/health")

        assert response.status_code == 503
        body = response.get_json()
        assert body["status"] == "unhealthy"
        assert body["components"]["database"] == "unavailable"

    def test_teardown_context_registered(self, app):
        """App should have a container attribute."""
        assert hasattr(app, 'container')


class TestStartupRoleSeeding:
    """An empty schema is a stage of setup, not an incident."""

    @staticmethod
    def _container(missing=(), fail_with=None, use_alembic=True):
        """Build a container whose database reports the given state.

        Args:
            missing: Table names the database does not have.
            fail_with: Exception the database raises when asked, if any.
            use_alembic: What the configuration says about ``USE_ALEMBIC``.
                Set rather than left to the mock, because a ``Mock``
                attribute is truthy and every assertion about the hint
                would hold for that reason alone.

        Returns:
            Tuple of (container, logger, db_manager).
        """
        logger = Mock()
        # MagicMock: `session()` is used as a context manager.
        db_manager = MagicMock()

        if fail_with is not None:
            db_manager.missing_tables.side_effect = fail_with
        else:
            db_manager.missing_tables.return_value = list(missing)

        container = Mock()
        container.config.USE_ALEMBIC = use_alembic
        container.get_logger.return_value = logger
        container.get_db_manager.return_value = db_manager
        return container, logger, db_manager

    def test_absent_schema_is_reported_without_alarm(self):
        """A database awaiting its first migration must not warn.

        Startup seeding runs in every process, so a warning here met the
        operator on every CLI command against a fresh database -- for a
        state the next command resolves.
        """
        container, logger, db_manager = self._container(
            missing=["roles", "permissions"]
        )

        with patch("link_shortener.web.app_factory.seed_base_roles") as seed:
            _seed_base_roles_if_ready(container)

        logger.warning.assert_not_called()
        logger.info.assert_called_once()
        # Nothing to seed into: the attempt is what produced the driver
        # error that got reported as a failure.
        seed.assert_not_called()
        db_manager.session.assert_not_called()

    def test_names_the_missing_tables_and_the_way_out(self):
        """The message has to be actionable, not merely quiet."""
        container, logger, _ = self._container(missing=["roles"])

        with patch("link_shortener.web.app_factory.seed_base_roles"):
            _seed_base_roles_if_ready(container)

        _, kwargs = logger.info.call_args
        assert "roles" in kwargs["missing_tables"]
        assert "load-base-roles" in kwargs["next_step"]
        # The hint has to name a command that exists: it said "flask db
        # upgrade", and that one never did.
        assert "flask alembic upgrade head" in kwargs["next_step"]

    def test_the_way_out_is_the_one_this_configuration_leaves_open(self):
        """``USE_ALEMBIC`` closes one of the two ways and opens the other.

        The hint named ``flask alembic upgrade head`` whatever the flag
        said, so a deployment running with it off was told, on every
        start until it had a schema, to run the one command that
        configuration refuses with exit 1 -- while ``flask db init``, the
        command that would have worked, went unmentioned.
        """
        container, logger, _ = self._container(
            missing=["roles"], use_alembic=False
        )

        with patch("link_shortener.web.app_factory.seed_base_roles"):
            _seed_base_roles_if_ready(container)

        _, kwargs = logger.info.call_args
        assert "flask db init" in kwargs["next_step"]
        assert "alembic" not in kwargs["next_step"]
        assert "load-base-roles" in kwargs["next_step"]

    def test_naming_the_way_out_does_not_warn_about_the_context(self):
        """The flag is read off the container, not off ``current_app``.

        Written the obvious way it reached for the request-time proxy,
        and this branch runs from the CLI too: the absent schema then
        came out as "AUTO_SEED_ROLES failed: Working outside of
        application context", which is a warning -- the one thing this
        function exists not to raise for a database awaiting setup.
        """
        container, logger, _ = self._container(
            missing=["roles"], use_alembic=False
        )

        with patch("link_shortener.web.app_factory.seed_base_roles"):
            _seed_base_roles_if_ready(container)

        logger.warning.assert_not_called()

    def test_ready_schema_is_seeded(self):
        """With the tables in place the seeding still has to happen."""
        container, logger, db_manager = self._container(missing=[])

        with patch("link_shortener.web.app_factory.seed_base_roles") as seed:
            _seed_base_roles_if_ready(container)

        session = db_manager.session.return_value.__enter__.return_value
        seed.assert_called_once_with(session)
        logger.warning.assert_not_called()

    def test_unreachable_database_still_warns(self):
        """Silencing the empty schema must not silence a real failure."""
        container, logger, _ = self._container(
            fail_with=OSError("connection refused")
        )

        with patch("link_shortener.web.app_factory.seed_base_roles"):
            _seed_base_roles_if_ready(container)

        logger.warning.assert_called_once()
        _, kwargs = logger.warning.call_args
        assert "connection refused" in kwargs["error"]
