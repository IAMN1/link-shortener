"""The command that sweeps registrations nobody confirmed.

A use case nothing calls is a use case that does not run. This one was
exactly that for a while: the class existed, the container built it, the
configuration validated its window against the token lifetime -- and no
command, schedule or route ever invoked it, so an unconfirmed
registration held its address for good. These tests are what make the
command's absence visible.
"""

from datetime import datetime, timedelta, timezone

import pytest
from flask.testing import FlaskCliRunner

from link_shortener.domain import Email, PasswordHash, User
from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.infrastructure.database.manager import DatabaseManager
from link_shortener.infrastructure.database.seed import seed_base_roles


HASH = "$2b$12$" + "x" * 53


class SweepConfig(TestingConfig):
    """Testing profile with a window short enough to write tests against."""

    LOGGING_ENABLED = False
    AUDIT_ENABLED = False
    AUTO_SEED_ROLES = False
    EMAIL_VERIFICATION_TTL_HOURS = 24
    UNVERIFIED_ACCOUNT_TTL_HOURS = 48


@pytest.fixture(scope="module")
def db_manager():
    """A database with the schema in place."""
    manager = DatabaseManager(
        database_url=SweepConfig.DATABASE_URL, echo=False, database_type="sqlite"
    )
    manager.connect()
    manager.create_tables()
    with manager.session() as session:
        seed_base_roles(session)

    yield manager
    manager.close()


@pytest.fixture(scope="module")
def app(db_manager):
    """Application bound to that database."""
    from link_shortener.web.app_factory import create_app

    application = create_app(config=SweepConfig())
    application.container.db_component._manager = db_manager
    return application


@pytest.fixture(scope="module")
def runner(app):
    """CLI runner bound to the app."""
    return FlaskCliRunner(app)


def _register(app, email, verified, age_hours):
    """Store one account of a given age and confirmation state."""
    user = User.create(
        email=Email(email), password_hash=PasswordHash(HASH), email_verified=verified
    )
    user.created_at = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    with app.app_context():
        with app.container.get_uow_factory()() as uow:
            uow.users.save(user)
            uow.commit()
    return user


def _exists(app, email):
    """Whether an account with this address is still there."""
    with app.app_context():
        with app.container.get_uow_factory()() as uow:
            return uow.users.find_by_email(Email(email)) is not None


class TestTheCommandExists:
    """It has to be reachable, or the sweep never runs anywhere."""

    def test_it_is_listed_among_the_maintenance_commands(self, runner, app):
        result = runner.invoke(app.cli, ["maintenance", "--help"])

        assert result.exit_code == 0
        assert "clean-unverified" in result.output

    def test_it_runs(self, runner, app):
        result = runner.invoke(app.cli, ["maintenance", "clean-unverified"])

        assert result.exit_code == 0, result.output


class TestWhatItSweeps:
    """Old and unconfirmed, and nothing else."""

    def test_it_deletes_an_old_unconfirmed_account(self, runner, app):
        _register(app, "cli-stale@example.test", verified=False, age_hours=100)

        result = runner.invoke(app.cli, ["maintenance", "clean-unverified"])

        assert result.exit_code == 0
        assert not _exists(app, "cli-stale@example.test")

    def test_it_reports_how_many_it_deleted(self, runner, app):
        _register(app, "cli-counted@example.test", verified=False, age_hours=100)

        result = runner.invoke(app.cli, ["maintenance", "clean-unverified"])

        assert "Deleted 1 unconfirmed accounts." in result.output

    def test_it_spares_an_account_still_within_the_window(self, runner, app):
        """48 hours is this profile's window; two hours old is waiting,
        not abandoned."""
        _register(app, "cli-waiting@example.test", verified=False, age_hours=2)

        runner.invoke(app.cli, ["maintenance", "clean-unverified"])

        assert _exists(app, "cli-waiting@example.test")

    def test_it_spares_confirmed_accounts_however_old(self, runner, app):
        """The failure that would take the whole user table with it."""
        _register(app, "cli-settled@example.test", verified=True, age_hours=10_000)

        runner.invoke(app.cli, ["maintenance", "clean-unverified"])

        assert _exists(app, "cli-settled@example.test")

    def test_the_address_can_be_registered_again_afterwards(self, runner, app):
        """What the sweep is for, stated as the owner of the address
        experiences it."""
        _register(app, "cli-reclaimed@example.test", verified=False, age_hours=100)

        runner.invoke(app.cli, ["maintenance", "clean-unverified"])
        _register(app, "cli-reclaimed@example.test", verified=False, age_hours=0)

        assert _exists(app, "cli-reclaimed@example.test")
