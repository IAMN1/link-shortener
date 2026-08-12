"""The commands that create an account or a link, and what they must produce.

These four paths had no test anywhere in the suite, and the gap was
measured rather than assumed: with ``is_active=is_active`` changed to
``is_active=False`` -- every account created disabled, nobody able to sign
in -- the whole suite still passed, and so it did with the role dropped,
with ``link create`` printing the original URL where the short one belongs,
and with the migration command announcing the database it was told not to
touch.

What is checked is the row rather than the wording, because the wording is
built from the entity the command has in hand and not from what the
database kept. Measured on the plainest form of that: with ``uow.commit()``
removed, ``create-user`` still exits 0 and still prints "User
nocommit@example.test created successfully (active: True)", and no such
account exists afterwards.
"""

import pytest
from flask.testing import FlaskCliRunner
from sqlalchemy import inspect

from link_shortener.domain.value_objects.email import Email
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.infrastructure.database.manager import DatabaseManager
from link_shortener.infrastructure.database.seed import seed_base_roles


class CreationConfig(TestingConfig):
    """Testing profile that seeds nothing on its own."""

    LOGGING_ENABLED = False
    AUDIT_ENABLED = False
    AUTO_SEED_ROLES = False


@pytest.fixture
def db_manager():
    """A database with the schema and the base roles in place."""
    manager = DatabaseManager(
        database_url=CreationConfig.DATABASE_URL,
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

    application = create_app(config=CreationConfig())
    application.container.db_component._manager = db_manager
    return application


@pytest.fixture
def runner(app):
    """CLI runner bound to the app."""
    return FlaskCliRunner(app)


def _stored_user(app, address):
    """Read an account back through the repository, or None."""
    with app.app_context():
        with app.container.get_uow_factory()() as uow:
            return uow.users.find_by_email(Email(address))


class TestCreateUser:
    """``flask create-user`` must produce an account that can be used."""

    def test_the_account_it_creates_is_active(self, runner, app):
        """An account created disabled is an account nobody can sign in to.

        The flag the command prints is read off the entity it just built,
        so it is a true statement about that object and no statement at all
        about what the database kept. The row is what this asserts.
        """
        result = runner.invoke(
            app.cli,
            ["create-user", "--email", "active-check@example.test",
             "--password", "Str0ng!Passw0rd", "--role", "user"],
        )

        assert result.exit_code == 0, result.output
        stored = _stored_user(app, "active-check@example.test")
        assert stored is not None
        assert stored.is_active is True

    def test_the_account_can_be_signed_in_to_with_the_password_given(
        self, runner, app
    ):
        """The password reaching the database has to be the one typed.

        Nothing above this notices otherwise: an account stored with a
        mangled password is active, carries its role, and reports itself
        created. Measured with ``password.strip().lower()`` slipped into
        the command, every assertion here but this one still passed, and
        the operator could not sign in with what they had just typed.

        Asked through ``authenticate``, which is what the login route
        calls, so this is the question the operator will be asking.
        """
        address = "signin-check@example.test"
        password = "Str0ng!Passw0rd"
        result = runner.invoke(
            app.cli,
            ["create-user", "--email", address,
             "--password", password, "--role", "user"],
        )

        assert result.exit_code == 0, result.output
        with app.app_context():
            auth = app.container.get_authentication_service()
            assert auth.authenticate(address, password) is not None
            # And not because authenticate says yes to anything.
            assert auth.authenticate(address, password.lower()) is None

    def test_the_role_it_was_asked_for_is_the_role_it_assigns(self, runner, app):
        """``--role`` is the whole point of the command.

        An account created with no role at all still signs in and still
        reads as an account; what it cannot do is anything that needs a
        permission, and nothing about the account says why.
        """
        result = runner.invoke(
            app.cli,
            ["create-user", "--email", "role-check@example.test",
             "--password", "Str0ng!Passw0rd", "--role", "analyst"],
        )

        assert result.exit_code == 0, result.output
        stored = _stored_user(app, "role-check@example.test")
        assert stored is not None
        # The exact list, not membership. "analyst in roles" is the same
        # assertion with the dangerous half removed: measured, it passes
        # while the command hands out ``["analyst", "admin"]``, which is an
        # administrator created by a command asked for an analyst. Nothing
        # here grants a second role legitimately -- this is the CLI, not
        # registration, where the default role is added on purpose.
        assert [r.name for r in stored.roles] == ["analyst"]

    def test_a_role_that_does_not_exist_stops_the_command(self, runner, app):
        """Refused rather than created role-less, and said out loud."""
        result = runner.invoke(
            app.cli,
            ["create-user", "--email", "no-such-role@example.test",
             "--password", "Str0ng!Passw0rd", "--role", "nosuchrole"],
        )

        assert result.exit_code == 1
        assert "nosuchrole" in result.output
        assert _stored_user(app, "no-such-role@example.test") is None


class TestCreateAdmin:
    """``flask create-admin`` must produce an administrator, not a user."""

    def test_it_creates_an_active_account_holding_the_admin_role(
        self, runner, app
    ):
        """The role is the difference between this command and create-user.

        Without it the command is an expensive way to make an ordinary
        account, and the deployment that ran it has no administrator while
        being told it has one.
        """
        result = runner.invoke(
            app.cli,
            ["create-admin", "--email", "admin-check@example.test",
             "--password", "Str0ng!Passw0rd"],
        )

        assert result.exit_code == 0, result.output
        stored = _stored_user(app, "admin-check@example.test")
        assert stored is not None
        assert stored.is_active is True
        assert [r.name for r in stored.roles] == ["admin"]

        # This command is how a fresh deployment gets its first
        # administrator, so an account nobody can sign in to is the same as
        # no administrator at all.
        with app.app_context():
            auth = app.container.get_authentication_service()
            assert auth.authenticate(
                "admin-check@example.test", "Str0ng!Passw0rd"
            ) is not None


class TestLinkCreate:
    """``flask link create`` must report the link it made."""

    def test_it_prints_the_short_link_and_not_the_target(self, runner, app):
        """The short URL is the one thing the command exists to hand over.

        Printing the target instead is invisible in the exit code and in
        every other line: the command still succeeds, still names a code,
        and the operator copies an address that shortens nothing.
        """
        target = "https://example.test/a-page-to-shorten"
        result = runner.invoke(app.cli, ["link", "create", "--url", target])

        assert result.exit_code == 0, result.output

        codes = [
            line.split("Short code:")[1].strip()
            for line in result.output.splitlines()
            if "Short code:" in line
        ]
        assert len(codes) == 1
        code = codes[0]

        short_url_lines = [
            line for line in result.output.splitlines() if "Short URL:" in line
        ]
        assert len(short_url_lines) == 1
        short_url = short_url_lines[0].split("Short URL:")[1].strip()

        # The line has to carry the code that was just issued, and must not
        # be the target dressed up as a result.
        assert short_url.endswith(code)
        assert short_url != target
        assert target not in short_url

        with app.app_context():
            with app.container.get_uow_factory()() as uow:
                stored = uow.links.find_by_code(ShortCode(code))
        assert stored is not None
        assert stored.original_url.value == target

    def test_the_code_asked_for_is_the_code_issued(self, runner, app):
        """``--code`` is a request the command must honour or refuse.

        Silently issuing a generated code instead is invisible in the exit
        status and in every printed line, and the operator who asked for a
        branded code walks away with a random one -- usually after
        publishing the one they asked for.
        """
        result = runner.invoke(
            app.cli,
            ["link", "create", "--url", "https://example.test/branded",
             "--code", "launch2026"],
        )

        assert result.exit_code == 0, result.output
        assert "Short code: launch2026" in result.output

        with app.app_context():
            with app.container.get_uow_factory()() as uow:
                stored = uow.links.find_by_code(ShortCode("launch2026"))
        assert stored is not None
        assert stored.original_url.value == "https://example.test/branded"

    def test_the_link_it_makes_belongs_to_nobody_and_does_not_expire(
        self, runner, app
    ):
        """A link made from the command line is not a guest's link.

        The command builds a context with neither an account nor an
        address, and that is deliberate: charged to a guest instead, a CLI
        link takes a seven-day expiry nobody asked for and spends an
        allowance counted per address, so the eleventh ``link create`` on a
        host answers "Guest link limit of 10 exceeded". Measured with one
        extra argument -- ``remote_addr="127.0.0.1"`` on the context -- and
        the suite stayed green throughout.
        """
        result = runner.invoke(
            app.cli, ["link", "create", "--url", "https://example.test/from-the-cli"]
        )
        assert result.exit_code == 0, result.output

        code = [
            line.split("Short code:")[1].strip()
            for line in result.output.splitlines()
            if "Short code:" in line
        ][0]

        with app.app_context():
            with app.container.get_uow_factory()() as uow:
                stored = uow.links.find_by_code(ShortCode(code))

        assert stored is not None
        assert stored.owner is None
        assert stored.guest_identifier is None
        assert stored.expires_at is None

    def test_it_says_when_the_link_was_not_new(self, runner, app):
        """The second call deduplicates, and the report has to show it."""
        target = "https://example.test/asked-for-twice"

        first = runner.invoke(app.cli, ["link", "create", "--url", target])
        second = runner.invoke(app.cli, ["link", "create", "--url", target])

        assert first.exit_code == 0, first.output
        assert second.exit_code == 0, second.output
        assert "Is new: True" in first.output
        assert "Is new: False" in second.output


class TestMigrateWithoutAlembic:
    """``flask db migrate`` with Alembic off must not name the database."""

    def test_it_neither_migrates_nor_announces_the_database(self, runner, app):
        """It must leave the schema alone, and say nothing about where it is.

        Both halves are asserted because the wording alone is no evidence
        of the deed: measured, a ``drop_all`` added to this branch took
        every table with it while the command still exited 0 and still
        printed "Alembic is disabled", and the text-only version of this
        test stayed green.

        Announcing the database is the smaller half, and not free either:
        the URL carries the host and the user, and this branch has no
        reason to put a connection string into a deployment log.
        ``TestingConfig`` runs with ``USE_ALEMBIC`` off, which is exactly
        the branch under test.
        """
        assert app.config.get("USE_ALEMBIC") is False

        with app.app_context():
            engine = app.container.get_db_manager().engine
            before = set(inspect(engine).get_table_names())
        assert "users" in before, "the fixture is supposed to have a schema"

        result = runner.invoke(app.cli, ["db", "migrate"])

        assert result.exit_code == 0, result.output
        assert "Alembic is disabled" in result.output
        assert "sqlite" not in result.output.lower()
        assert "Database:" not in result.output

        with app.app_context():
            after = set(inspect(app.container.get_db_manager().engine).get_table_names())
        assert after == before
