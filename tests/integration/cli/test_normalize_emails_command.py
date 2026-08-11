"""The command that lowers addresses written before normalisation.

``Email`` lowers what it holds, which fixes the future and strands the
past: an account stored as ``Case@Example.com`` is no longer found by a
lookup for it. Its owner cannot sign in, and registering the address again
finds nothing and creates a second account for the same mailbox. This
command is the way out, so these tests hold what it does and -- more
importantly -- what it refuses to do.

The rows are written with SQL rather than through the repository, because
the repository cannot produce them any more: ``Email`` would lower them on
the way in. That is the same reason the command reads with SQL.
"""

import pytest
from flask.testing import FlaskCliRunner
from sqlalchemy import text

from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.infrastructure.database.manager import DatabaseManager
from link_shortener.infrastructure.database.seed import seed_base_roles


HASH = "$2b$12$" + "x" * 53


class NormaliseConfig(TestingConfig):
    """Testing profile with its own database file."""

    LOGGING_ENABLED = False
    AUDIT_ENABLED = False
    AUTO_SEED_ROLES = False


@pytest.fixture
def db_manager():
    """A database with the schema in place, fresh for each test."""
    manager = DatabaseManager(
        database_url=NormaliseConfig.DATABASE_URL,
        echo=False,
        database_type="sqlite",
    )
    manager.connect()
    manager.create_tables()
    with manager.session() as session:
        seed_base_roles(session)

    yield manager
    manager.close()


@pytest.fixture
def app(db_manager):
    """Application bound to that database."""
    from link_shortener.web.app_factory import create_app

    application = create_app(config=NormaliseConfig())
    application.container.db_component._manager = db_manager
    return application


@pytest.fixture
def runner(app):
    """CLI runner bound to the app."""
    return FlaskCliRunner(app)


def _store(app, *addresses):
    """Write accounts with the addresses exactly as given."""
    with app.app_context():
        with app.container.get_db_manager().session() as session:
            for index, address in enumerate(addresses):
                session.execute(
                    text(
                        "INSERT INTO users "
                        "(id, email, password_hash, is_active, "
                        " email_verified, created_at) "
                        "VALUES (:id, :email, :hash, 1, 1, CURRENT_TIMESTAMP)"
                    ),
                    {"id": f"u{index}", "email": address, "hash": HASH},
                )
            session.commit()


def _stored(app):
    """Every address in the table, as stored."""
    with app.app_context():
        with app.container.get_db_manager().session() as session:
            return sorted(
                session.execute(text("SELECT email FROM users")).scalars().all()
            )


class TestTheCommandExists:
    """Unreachable, it fixes nothing anywhere."""

    def test_it_is_listed_among_the_maintenance_commands(self, runner, app):
        result = runner.invoke(app.cli, ["maintenance", "--help"])

        assert result.exit_code == 0
        assert "normalize-emails" in result.output

    def test_it_runs_on_an_untouched_database(self, runner, app):
        result = runner.invoke(app.cli, ["maintenance", "normalize-emails"])

        assert result.exit_code == 0, result.output
        assert "already lower case" in result.output


class TestItChangesNothingUnlessTold:
    """A report by default: this rewrites the column identity lives in."""

    def test_a_plain_run_leaves_the_rows_alone(self, runner, app):
        _store(app, "Case@Example.test")

        result = runner.invoke(app.cli, ["maintenance", "normalize-emails"])

        assert result.exit_code == 0, result.output
        assert _stored(app) == ["Case@Example.test"]

    def test_a_plain_run_says_what_it_would_do(self, runner, app):
        _store(app, "Case@Example.test")

        result = runner.invoke(app.cli, ["maintenance", "normalize-emails"])

        assert "case@example.test" in result.output
        assert "1 to change" in result.output


class TestWithApply:
    """What it lowers, and what it will not touch."""

    def test_it_lowers_an_address(self, runner, app):
        _store(app, "Case@Example.test")

        result = runner.invoke(
            app.cli, ["maintenance", "normalize-emails", "--apply"]
        )

        assert result.exit_code == 0, result.output
        assert _stored(app) == ["case@example.test"]

    def test_the_account_becomes_reachable_again(self, runner, app):
        """The point of the exercise: before it runs, this account cannot
        be found by any spelling at all.

        Reachability, not sign-in: the row is written with a fixed hash no
        password matches, so signing in could not succeed here whatever
        the lookup did.
        """
        from link_shortener.domain import Email

        _store(app, "Case@Example.test")
        runner.invoke(app.cli, ["maintenance", "normalize-emails", "--apply"])

        with app.app_context():
            with app.container.get_uow_factory()() as uow:
                assert uow.users.find_by_email(Email("Case@Example.test"))

    def test_a_clash_is_left_untouched(self, runner, app):
        """Both spellings already exist as separate accounts. Lowering one
        onto the other means choosing whose links, roles and sessions
        survive -- an owner's decision, not a maintenance command's."""
        _store(app, "Clash@example.test", "clash@example.test")

        result = runner.invoke(
            app.cli, ["maintenance", "normalize-emails", "--apply"]
        )

        assert result.exit_code == 0, result.output
        assert _stored(app) == ["Clash@example.test", "clash@example.test"]

    def test_a_clash_is_reported(self, runner, app):
        _store(app, "Clash@example.test", "clash@example.test")

        result = runner.invoke(
            app.cli, ["maintenance", "normalize-emails", "--apply"]
        )

        assert "another account also lowers to" in result.output

    def test_a_clash_does_not_stop_the_others(self, runner, app):
        """One conflict must not leave every other account stranded."""
        _store(
            app,
            "Clash@example.test",
            "clash@example.test",
            "Fine@example.test",
        )

        runner.invoke(app.cli, ["maintenance", "normalize-emails", "--apply"])

        assert "fine@example.test" in _stored(app)


class TestAPairWithNoLowerCaseMemberYet:
    """Two spellings that both need lowering collide with each other.

    The first version of this command looked for a collision by asking
    whether the lower-case spelling was *already stored*. This pair has no
    lower-case member at all, so both rows were reported safe, the update
    hit the unique index, and -- one transaction for the whole run -- every
    unrelated address stayed unmigrated while the operator had just been
    told there were no conflicts.
    """

    ADDRESSES = ("Case@Example.test", "CASE@Example.test")

    def test_both_are_reported_as_conflicting(self, runner, app):
        _store(app, *self.ADDRESSES)

        result = runner.invoke(app.cli, ["maintenance", "normalize-emails"])

        assert "2 in conflict" in result.output
        assert "0 to change" in result.output

    def test_neither_is_touched(self, runner, app):
        _store(app, *self.ADDRESSES)

        result = runner.invoke(
            app.cli, ["maintenance", "normalize-emails", "--apply"]
        )

        assert result.exit_code == 0, result.output
        assert _stored(app) == sorted(self.ADDRESSES)

    def test_an_unrelated_address_still_migrates(self, runner, app):
        """The failure that mattered: one bad pair used to strand the
        whole database, because every update shared one transaction."""
        _store(app, *self.ADDRESSES, "Fine@example.test")

        result = runner.invoke(
            app.cli, ["maintenance", "normalize-emails", "--apply"]
        )

        assert result.exit_code == 0, result.output
        assert "fine@example.test" in _stored(app)
