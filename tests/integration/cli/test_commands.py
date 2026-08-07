"""Integration tests for CLI commands."""
import pytest
from datetime import timedelta
from unittest.mock import MagicMock
from flask.testing import FlaskCliRunner
from link_shortener.domain.entities.user import User
from link_shortener.domain.value_objects.email import Email
from link_shortener.domain.value_objects.password_hash import PasswordHash
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

    def test_security_check_secrets_reports_missing(self, runner, app, monkeypatch):
        """Should exit non-zero when a required secret is not configured."""
        monkeypatch.delenv("SECRET_KEY", raising=False)
        monkeypatch.delenv("SHORT_CODE_PEPPER", raising=False)

        result = runner.invoke(app.cli, ["security", "check-secrets"])

        # Non-zero so the command is usable as a deployment gate.
        assert result.exit_code == 1
        assert "SECRET_KEY" in result.output
        assert "MISSING" in result.output

    def test_security_check_secrets_passes_when_configured(
        self, runner, app, monkeypatch
    ):
        """Should exit zero once both secrets are present."""
        monkeypatch.setenv("SECRET_KEY", "configured-secret")
        monkeypatch.setenv("SHORT_CODE_PEPPER", "configured-pepper")

        result = runner.invoke(app.cli, ["security", "check-secrets"])

        assert result.exit_code == 0
        assert "MISSING" not in result.output

    def test_validate_token_names_the_token_type(self, runner, app):
        """The verdict must say which kind of token was validated.

        A bare "Token is VALID" read the same for an access token and a
        refresh token. They are not interchangeable -- a refresh token
        authenticates no request -- so an operator checking one and reading
        "VALID" was being told the opposite of what holds.
        """
        with app.app_context():
            auth_service = app.container.get_authentication_service()
            user = User(
                id="cli-token-user",
                email=Email("token-check@example.com"),
                password_hash=PasswordHash(auth_service.hash_password("CliCheck123!")),
                roles=[],
            )
            refresh = auth_service._create_token(
                user, timedelta(days=1), "refresh", token_id="cli-jti"
            )
            access = auth_service._create_token(
                user, timedelta(minutes=5), "access", session_id="cli-sid"
            )

            refresh_result = runner.invoke(
                app.cli, ["security", "validate-token", refresh]
            )
            access_result = runner.invoke(
                app.cli, ["security", "validate-token", access]
            )

        assert refresh_result.exit_code == 0
        assert "refresh" in refresh_result.output
        # And says plainly that it opens nothing.
        assert "authenticates no request" in refresh_result.output

        assert access_result.exit_code == 0
        assert "access" in access_result.output
        assert "authenticates no request" not in access_result.output

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

    def test_alembic_status_ignores_ambient_database_url(
        self, runner, app, monkeypatch
    ):
        """Alembic must target the app's database, not the environment's.

        The command runs alembic in a subprocess, and a subprocess inherits
        the ambient environment rather than the configuration of the
        application that launched it. The ``testing`` profile pins in-memory
        SQLite precisely so a test run cannot reach a real database, and an
        exported ``DATABASE_URL`` used to overrule it.

        The ambient value names a dialect that does not exist, so if it were
        consulted the run would fail immediately and for an unmistakable
        reason -- no network, no timeout.
        """
        monkeypatch.setenv("DATABASE_URL", "bogus://nowhere")

        result = runner.invoke(app.cli, ["alembic", "status"])

        assert result.exit_code == 0, result.output

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
