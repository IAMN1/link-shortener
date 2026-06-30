"""Integration tests for CLI commands."""
import pytest
from unittest.mock import MagicMock
from flask.testing import FlaskCliRunner
from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.infrastructure.database.manager import DatabaseManager
from link_shortener.infrastructure.database.seed import seed_base_roles


class TestConfig(TestingConfig):
    """Config for CLI integration tests."""
    LOGGING_ENABLED = False
    AUDIT_ENABLED = False
    AUTO_SEED_ROLES = False


@pytest.fixture(scope="module")
def db_manager():
    """Create a database manager with tables pre-created."""
    config = TestConfig()
    manager = DatabaseManager(
        database_url=config.DATABASE_URL,
        echo=False,
        database_type="sqlite",
    )
    manager.connect()
    manager.create_tables()

    # Seed base roles so CLI commands that need them work
    with manager.session() as session:
        seed_base_roles(session)

    yield manager
    manager.close()


@pytest.fixture(scope="module")
def app(db_manager):
    """Create application with pre-seeded database."""
    from link_shortener.web.app_factory import create_app

    app = create_app(config=TestConfig())

    # Replace the container's db component so it uses our pre-seeded manager
    app.container.db_component._manager = db_manager

    return app


@pytest.fixture(scope="module")
def runner(app):
    """Create a CLI runner bound to the app."""
    return FlaskCliRunner(app)


class TestDatabaseCommands:
    """Test database CLI commands."""

    def test_db_check(self, runner, app):
        result = runner.invoke(app.cli, ["db", "check"])
        assert result.exit_code == 0
        assert "healthy" in result.output.lower() or "failed" in result.output.lower()

    def test_db_status(self, runner, app):
        result = runner.invoke(app.cli, ["db", "status"])
        assert result.exit_code == 0

    def test_db_help(self, runner, app):
        result = runner.invoke(app.cli, ["db", "--help"])
        assert result.exit_code == 0
        assert "Database management" in result.output


class TestSecurityCommands:
    """Test security CLI commands."""

    def test_security_check_secrets(self, runner, app):
        result = runner.invoke(app.cli, ["security", "check-secrets"])
        assert result.exit_code == 0
        assert "SECRET_KEY" in result.output

    def test_security_generate_secrets(self, runner, app):
        result = runner.invoke(app.cli, ["security", "generate-secrets"])
        assert result.exit_code == 0
        assert "SECRET_KEY=" in result.output
        assert "SHORT_CODE_PEPPER=" in result.output

    def test_security_list_roles(self, runner, app):
        with app.app_context():
            result = runner.invoke(app.cli, ["security", "list-roles"])
            assert result.exit_code == 0

    def test_security_list_users(self, runner, app):
        with app.app_context():
            result = runner.invoke(app.cli, ["security", "list-users"])
            assert result.exit_code == 0

    def test_security_help(self, runner, app):
        result = runner.invoke(app.cli, ["security", "--help"])
        assert result.exit_code == 0
        assert "Security management" in result.output


class TestAlembicCommands:
    """Test alembic CLI commands."""

    def test_alembic_status(self, runner, app):
        result = runner.invoke(app.cli, ["alembic", "status"])
        assert result.exit_code == 0

    def test_alembic_help(self, runner, app):
        result = runner.invoke(app.cli, ["alembic", "--help"])
        assert result.exit_code == 0
        assert "Alembic migration" in result.output


class TestMaintenanceCommands:
    """Test maintenance CLI commands."""

    def test_maintenance_health(self, runner, app):
        result = runner.invoke(app.cli, ["maintenance", "health"])
        assert result.exit_code in [0, 1]

    def test_maintenance_check_redis(self, runner, app):
        result = runner.invoke(app.cli, ["maintenance", "check-redis"])
        assert result.exit_code == 0
        assert "redis" in result.output.lower()

    def test_maintenance_help(self, runner, app):
        result = runner.invoke(app.cli, ["maintenance", "--help"])
        assert result.exit_code == 0
        assert "Maintenance" in result.output


class TestCacheCommands:
    """Test cache CLI commands."""

    def test_cache_stats(self, runner, app):
        result = runner.invoke(app.cli, ["cache", "stats"])
        assert result.exit_code == 0

    def test_cache_help(self, runner, app):
        result = runner.invoke(app.cli, ["cache", "--help"])
        assert result.exit_code == 0
        assert "Cache" in result.output


class TestStatsCommands:
    """Test stats CLI commands."""

    def test_stats_show(self, runner, app):
        result = runner.invoke(app.cli, ["stats", "show"])
        assert result.exit_code == 0
        assert "SERVICE STATISTICS" in result.output

    def test_stats_help(self, runner, app):
        result = runner.invoke(app.cli, ["stats", "--help"])
        assert result.exit_code == 0
        assert "Statistics" in result.output
