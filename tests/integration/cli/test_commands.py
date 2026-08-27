"""Integration tests for CLI commands."""
import pathlib
import re

import pytest
from unittest.mock import MagicMock
from datetime import timedelta
from flask.testing import FlaskCliRunner
from link_shortener.application.context import RequestContext
from link_shortener.domain.entities.user import User
from link_shortener.domain.value_objects.email import Email
from link_shortener.domain.value_objects.password_hash import PasswordHash
from link_shortener.application.ports.cache.service_cache import ServiceCache
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
        # The disjunction that stood here was already dead: the failure
        # branch exits 1, and the assertion above rules that out, so
        # "failed" could never appear. Naming the one word that can.
        assert "healthy" in result.output.lower()

    def test_db_check_names_the_reason_it_could_not_connect(
        self, runner, app
    ):
        """One sentence for every cause is not a diagnosis.

        This is the command an operator runs to find out what is wrong,
        and one answer for a wrong password, an unreachable host and a
        database that does not exist tells the operator nothing: with the
        reason caught and dropped, a wrong password in the docker stack
        produces no "password authentication failed" anywhere.
        """
        from sqlalchemy.exc import OperationalError

        class _Unreachable:
            def session(self):
                raise OperationalError(
                    "SELECT 1",
                    {},
                    Exception('password authentication failed for user "x"'),
                )

        real = app.container.db_component._manager
        app.container.db_component._manager = _Unreachable()
        try:
            result = runner.invoke(app.cli, ["db", "check"])
        finally:
            app.container.db_component._manager = real

        assert result.exit_code == 1
        assert "password authentication failed" in result.stderr, result.stderr
        assert "SELECT 1" not in result.output, "the statement leaked"

    def test_db_status(self, runner, app):
        result = runner.invoke(app.cli, ["db", "status"])
        assert result.exit_code == 0

    def test_db_status_refuses_the_same_way_db_check_does(self, runner, app):
        """The alias is held to the whole of what it is an alias for.

        It was a second copy of the same ten lines, and only ``db check``
        was ever tested against a database that does not answer -- so the
        copy could have been left behind by any fix to the original with
        the suite still green. They share one body now, and this is what
        says so from the outside.
        """
        from sqlalchemy.exc import OperationalError

        class _Unreachable:
            def session(self):
                raise OperationalError(
                    "SELECT 1", {}, Exception("could not connect to server")
                )

        real = app.container.db_component._manager
        app.container.db_component._manager = _Unreachable()
        try:
            result = runner.invoke(app.cli, ["db", "status"])
        finally:
            app.container.db_component._manager = real

        assert result.exit_code == 1
        assert "could not connect to server" in result.stderr, result.stderr
        assert "SELECT 1" not in result.output, "the statement leaked"

    def test_db_migrate_reports_a_failure_and_exits_one(self, runner, app):
        """The command that applies migrations says when it did not.

        Printing and exiting used to happen inside the logic module, and
        nothing exercised that path: a failed migration could have gone
        out as exit 0 with the reason on stdout, which is what a
        deployment script reads as success.
        """
        from link_shortener.infrastructure.cli.commands.alembic import (
            AlembicCommands,
        )

        # Alembic itself is stood in for; what is under test is the path
        # from it back to the shell. ``USE_ALEMBIC`` is False in this
        # profile, and the branch that runs migrations is the other one.
        real_flag = app.config["USE_ALEMBIC"]
        real_upgrade = AlembicCommands.upgrade
        app.config["USE_ALEMBIC"] = True
        AlembicCommands.upgrade = staticmethod(
            lambda *a, **k: (
                False,
                "Error: FAILED: target database is not up to date.",
            )
        )
        try:
            result = runner.invoke(app.cli, ["db", "migrate"])
        finally:
            AlembicCommands.upgrade = real_upgrade
            app.config["USE_ALEMBIC"] = real_flag

        assert result.exit_code == 1
        assert "not up to date" in result.stderr, result.stderr

    def test_db_help(self, runner, app):
        result = runner.invoke(app.cli, ["db", "--help"])
        assert result.exit_code == 0
        assert "Database management" in result.output


class TestSecurityCommands:
    """Test security CLI commands."""

    def test_check_secrets_names_what_is_missing_on_stderr(
        self, runner, app, monkeypatch
    ):
        """A deployment gate has to say why it closed.

        This is the command most likely to be run with its output
        redirected away -- that is what a gate in a pipeline looks like --
        and it exited 1 with the reason on stdout and nothing on stderr.
        The report itself stays where it was; the complaint moved.
        """
        monkeypatch.delenv("SECRET_KEY", raising=False)
        monkeypatch.delenv("SHORT_CODE_PEPPER", raising=False)

        result = runner.invoke(app.cli, ["security", "check-secrets"])

        assert result.exit_code == 1
        assert "SECRET_KEY" in result.stderr, result.stderr
        assert "SHORT_CODE_PEPPER" in result.stderr, result.stderr
        assert "generate-secrets" in result.stderr
        # The status table is the command's output and stays on stdout.
        assert "Secret Configuration Status" in result.stdout

    def test_check_secrets_says_nothing_on_stderr_when_they_are_set(
        self, runner, app, monkeypatch
    ):
        monkeypatch.setenv("SECRET_KEY", "x" * 32)
        monkeypatch.setenv("SHORT_CODE_PEPPER", "y" * 32)

        result = runner.invoke(app.cli, ["security", "check-secrets"])

        assert result.exit_code == 0, result.output
        assert result.stderr == "", result.stderr

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

    def test_generate_secrets_writes_the_file_without_echoing_it(
        self, runner, app, tmp_path
    ):
        """
        `--write` puts the values in the file and nowhere else.

        Printing them as well would undo the reason the flag exists: the
        setup guide can be a run of commands only if the secrets never
        need to be read off the screen, and a secret in the scrollback
        outlives the terminal it was printed in.
        """
        target = tmp_path / ".env"
        target.write_text("SECRET_KEY=\nSHORT_CODE_PEPPER=\n", encoding="utf-8")

        result = runner.invoke(
            app.cli, ["security", "generate-secrets", "--write", str(target)]
        )

        assert result.exit_code == 0, result.output
        written = target.read_text(encoding="utf-8")
        value = written.split("SECRET_KEY=", 1)[1].split("\n", 1)[0]
        assert len(value) == 64, written
        assert value not in result.output

    def test_generate_secrets_refuses_a_file_it_would_overwrite(
        self, runner, app, tmp_path
    ):
        """Non-zero, so a setup script stops rather than carrying on."""
        target = tmp_path / ".env"
        target.write_text("SECRET_KEY=already\n", encoding="utf-8")

        result = runner.invoke(
            app.cli, ["security", "generate-secrets", "--write", str(target)]
        )

        assert result.exit_code != 0
        assert "already" in target.read_text(encoding="utf-8")

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

    def test_validate_token_prints_the_expiry_as_a_date(self, runner, app):
        """
        `Expires: 1787072048` is a number, not a moment.

        Everything else this service writes about time is ISO 8601 in
        UTC -- the journals, the API, the charts -- and an operator
        checking a token had to convert an epoch by hand to answer the one
        question they asked it: how long is this good for.
        """
        with app.app_context():
            auth_service = app.container.get_authentication_service()
            user = User(
                id="cli-expiry-user",
                email=Email("expiry-check@example.com"),
                password_hash=PasswordHash(
                    auth_service.hash_password("CliCheck123!")
                ),
                roles=[],
            )
            token = auth_service._create_token(
                user, timedelta(minutes=5), "access", session_id="cli-exp"
            )

            result = runner.invoke(app.cli, ["security", "validate-token", token])

        assert result.exit_code == 0, result.output
        expires = [
            line for line in result.output.splitlines()
            if line.startswith("Expires:")
        ]
        assert expires, result.output
        assert re.search(
            r"Expires: \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", expires[0]
        ), expires[0]

    def test_security_generate_secrets(self, runner, app):
        result = runner.invoke(app.cli, ["security", "generate-secrets"])
        assert result.exit_code == 0
        assert "SECRET_KEY=" in result.output
        assert "SHORT_CODE_PEPPER=" in result.output

    def test_security_list_roles(self, runner, app):
        with app.app_context():
            result = runner.invoke(app.cli, ["security", "list-roles"])
            assert result.exit_code == 0

    def test_list_roles_keeps_its_columns_under_a_long_description(
        self, runner, app
    ):
        """
        A table is a table only while the columns line up.

        `{description:<30}` pads a short value and does nothing at all to
        a long one, so one wordy role pushed its own permissions column
        past every other row's and the table stopped being readable at the
        row that mattered most.
        """
        with app.app_context():
            admin = app.container.get_admin_service()
            context = RequestContext(request_id="cli-test")
            admin.create_role("terse", "Short", [], context)
            admin.create_role(
                "wordy",
                "A description long enough to run past the column it was "
                "given, which is the whole point of this row",
                [],
                context,
            )

            result = runner.invoke(app.cli, ["security", "list-roles"])

        assert result.exit_code == 0, result.output
        columns = {
            name: line.index("none")
            for name in ("terse", "wordy")
            for line in result.output.splitlines()
            if f" {name} " in line and "none" in line
        }

        assert set(columns) == {"terse", "wordy"}, result.output
        # Two rows, one column. Both are asserted because a check reading
        # only the long row passes on a table with one row in it.
        assert columns["terse"] == columns["wordy"], result.output

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
        SQLite precisely so a test run cannot reach a real database, and
        an exported ``DATABASE_URL`` must not overrule it.

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
        # `in [0, 1]` accepted the failing exit code the command uses to
        # report an unhealthy service, so it could not tell the two apart.
        assert result.exit_code == 0
        # The verdict, not just the word: the line is printed either way,
        # with OK or FAILED after it, so the name alone asserts only that
        # the command produced its usual output. The names are padded to
        # one column now, so the space between is not fixed.
        assert re.search(r"^Database: +OK$", result.output, re.M), result.output
        # Every dependency the probe reads, which is what the command
        # promises and what it used not to do -- see
        # `test_the_health_command_and_the_probe_agree.py`.
        for name in ("Cache", "Task queue", "Rate limiter"):
            assert re.search(rf"^{name}: ", result.output, re.M), result.output

    def test_maintenance_check_redis(self, runner, app):
        """With no backend configured the command says so and exits 0.

        The word "redis" used to be the whole assertion, and the command
        printed it in all three of its branches -- so the test passed
        whether the answer was "healthy", "failed" or "disabled".
        """
        result = runner.invoke(app.cli, ["maintenance", "check-redis"])

        assert result.exit_code == 0
        assert "No cache backend is configured." in result.output

    def test_check_redis_asks_the_cache_rather_than_remembering(self):
        """A backend that has gone away is reported as gone.

        The command reached for ``RedisLinkCache._ensure_connection``,
        which is documented to answer from what it holds rather than by
        asking: a cache with a client and its "available" flag still set
        answered ``True`` for a server that was no longer there. Measured
        against the same cache, ``ping()`` answers ``False``.
        """
        from redis.exceptions import ConnectionError as RedisDown

        from link_shortener.infrastructure.cache.redis_cache import (
            RedisLinkCache,
        )
        from link_shortener.infrastructure.cli.commands.cache import (
            cache_health,
        )

        class DeadBackend:
            """A client that was up and whose server has since gone away."""

            def ping(self):
                raise RedisDown("Connection refused")

        cache = RedisLinkCache(
            redis_url="redis://127.0.0.1:1/0",
            prefix="probe",
            logger=MagicMock(),
            link_ttl=60,
            stats_ttl=60,
            connect_timeout=1,
            socket_timeout=1,
            retry_interval=1,
            secret_key="x" * 32,
        )
        # The state a cache is in after one successful operation.
        cache._client = DeadBackend()
        cache._available = True

        configured, alive = cache_health(cache)

        assert configured is True
        assert alive is False

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


class TestTheCacheCommandsAnswerFromTheCache:
    """What the cache says about itself is what these commands report.

    All three used to be worked out from somewhere else: whether a
    backend was expected came from ``REDIS_ENABLED`` and ``CACHE_ENABLED``
    rather than from ``is_configured()``, and whether it was up came from
    a private method of one implementation rather than from ``ping()``.
    Two expressions of one question drift, and this one had already
    drifted from the one ``maintenance health`` uses.
    """

    @staticmethod
    def _cache(configured, alive, info=None):
        """A stand-in answering the two questions of ``CacheHealth``."""
        cache = MagicMock(spec=ServiceCache)
        cache.is_configured.return_value = configured
        cache.ping.return_value = alive
        cache.get_cache_info.return_value = info or {}
        return cache

    @staticmethod
    def _with_cache(app, cache):
        """Hand a prepared cache to the container for one call."""
        component = app.container.cache_component
        original = component._cache
        component._cache = cache
        return original

    def test_a_backend_that_answers_is_reported_healthy(self, runner, app):
        real = self._with_cache(app, self._cache(configured=True, alive=True))
        try:
            result = runner.invoke(app.cli, ["maintenance", "check-redis"])
        finally:
            app.container.cache_component._cache = real

        assert result.exit_code == 0, result.output
        assert "healthy" in result.output

    def test_a_backend_that_does_not_answer_exits_one(self, runner, app):
        """The case the command exists for, and the one it used to miss.

        ``_ensure_connection`` answers from the client it is holding, so a
        cache whose server had gone away was still reported healthy --
        while ``maintenance health``, which asks ``ping()``, reported it
        failed in the same second.
        """
        real = self._with_cache(app, self._cache(configured=True, alive=False))
        try:
            result = runner.invoke(app.cli, ["maintenance", "check-redis"])
        finally:
            app.container.cache_component._cache = real

        assert result.exit_code == 1
        assert "did not answer" in result.stderr, result.stderr

    def test_cache_stats_exits_non_zero_when_the_cache_cannot_answer(
        self, runner, app
    ):
        """It printed the failure to stdout and exited 0.

        ``db check`` and ``check-redis`` both exit non-zero on the same
        kind of outage, so a monitoring line running this one could not
        tell a cache that answered from one that did not.
        """
        cache = self._cache(
            configured=True, alive=True, info={"error": "Redis unavailable"}
        )
        real = self._with_cache(app, cache)
        try:
            result = runner.invoke(app.cli, ["cache", "stats"])
        finally:
            app.container.cache_component._cache = real

        assert result.exit_code == 1
        assert "Redis unavailable" in result.stderr, result.stderr


class TestTheAlembicCommandsRefuseOnTheRightStream:
    """A failure goes to stderr, whichever of the five ran.

    Three of them printed it to stdout. The split was the same two
    against three as the one inside ``AlembicCommands`` -- ``status`` and
    ``history`` fixed, ``upgrade``, ``downgrade`` and ``migrate`` not --
    and it survived the fix to that one, because what was corrected there
    was which stream alembic is *read* from and this is which stream the
    operator is *written* to. A deployment script reading stderr for the
    reason a migration failed found it empty and the exit code 1.
    """

    ALEMBIC_COMMANDS = [
        (["alembic", "status"], "status"),
        (["alembic", "history"], "history"),
        (["alembic", "upgrade", "head"], "upgrade"),
        (["alembic", "downgrade", "-1"], "downgrade"),
        (["alembic", "migrate", "a message"], "migrate"),
    ]

    @pytest.fixture
    def alembic_refusing(self, app):
        """Every wrapper answers a failure, and the flag lets them run."""
        from link_shortener.infrastructure.cli.commands.alembic import (
            AlembicCommands,
        )

        answer = staticmethod(lambda *a, **k: (False, "Error: FAILED: no such revision"))
        originals = {}
        for name in ("status", "history", "upgrade", "downgrade", "migrate"):
            originals[name] = getattr(AlembicCommands, name)
            setattr(AlembicCommands, name, answer)
        was = app.config["USE_ALEMBIC"]
        app.config["USE_ALEMBIC"] = True
        yield
        app.config["USE_ALEMBIC"] = was
        for name, original in originals.items():
            setattr(AlembicCommands, name, original)

    @pytest.mark.parametrize("argv, name", ALEMBIC_COMMANDS)
    def test_the_reason_reaches_stderr(
        self, runner, app, alembic_refusing, argv, name
    ):
        result = runner.invoke(app.cli, argv)

        assert result.exit_code == 1, result.output
        assert "no such revision" in result.stderr, f"{name}: {result.stderr!r}"

    @pytest.mark.parametrize("argv, name", ALEMBIC_COMMANDS)
    def test_the_reason_is_not_on_stdout(
        self, runner, app, alembic_refusing, argv, name
    ):
        """Kept apart from the check above: a command that wrote to both
        streams would satisfy it and still put the failure where a script
        reading stdout takes it for output."""
        result = runner.invoke(app.cli, argv)

        assert "no such revision" not in result.stdout, name


class TestTheAlembicGroupHonoursTheFlag:
    """With ``USE_ALEMBIC`` off, a schema change is refused rather than run.

    ``db init`` builds the tables straight from the models and writes no
    revision, so a database built that way and then migrated tries to
    create tables that already exist. The refusal is what keeps the two
    ways of building a schema from being mixed, and no test had ever
    taken it.
    """

    @pytest.mark.parametrize(
        "argv",
        [
            ["alembic", "upgrade", "head"],
            ["alembic", "downgrade", "-1"],
            ["alembic", "migrate", "a message"],
        ],
    )
    def test_a_schema_change_is_refused(self, runner, app, argv):
        assert app.config["USE_ALEMBIC"] is False, "the profile changed"

        result = runner.invoke(app.cli, argv)

        assert result.exit_code == 1
        assert "USE_ALEMBIC is disabled" in result.stderr, result.stderr
        # The way out is named, and it is the pair that does honour the
        # flag rather than "enable Alembic".
        assert "flask db init" in result.stderr

    @pytest.mark.parametrize("argv", [["alembic", "status"], ["alembic", "history"]])
    def test_reading_is_not_refused(self, runner, app, argv):
        """The flag guards schema changes, not questions about them."""
        result = runner.invoke(app.cli, argv)

        assert "USE_ALEMBIC is disabled" not in result.output


class TestASwitchedOffCacheIsNotABrokenCache:
    """The three commands that look at the cache agree about "off".

    ``cache stats`` was the one that disagreed, and only after this slice
    gave it a failing exit code: ``NullCache`` reports itself with an
    ``error`` key, so the documented local setup -- ``REDIS_ENABLED`` and
    ``CACHE_ENABLED`` both off -- got exit 1 from an install that is
    working exactly as configured, and any monitoring line reading the
    code went red over it.
    """

    @pytest.fixture
    def app_without_cache(self, db_manager):
        """An application with caching switched off entirely."""
        from link_shortener.web.app_factory import create_app

        class NoCache(TestConfig):
            CACHE_ENABLED = False
            REDIS_ENABLED = False

        application = create_app(config=NoCache())
        application.container.db_component._manager = db_manager
        return application

    @pytest.mark.parametrize(
        "argv",
        [["cache", "stats"], ["maintenance", "check-redis"]],
    )
    def test_it_exits_zero_and_says_there_is_no_backend(
        self, app_without_cache, argv
    ):
        runner = FlaskCliRunner(app_without_cache)

        result = runner.invoke(args=argv)

        assert result.exit_code == 0, result.output
        assert "No cache backend is configured." in result.output

    def test_the_health_command_agrees_with_them(self, app_without_cache):
        """The third surface on the same question, and the one the other
        two were brought into line with."""
        runner = FlaskCliRunner(app_without_cache)

        result = runner.invoke(args=["maintenance", "health"])

        assert result.exit_code == 0, result.output
        assert re.search(r"^Cache: +not configured$", result.output, re.M), (
            result.output
        )


class TestTheRefusalsOperatorsActuallyMeet:
    """The other half of four commands, which nothing had ever run.

    Each of these is the branch a person reaches by making the ordinary
    mistake -- a token that has expired, a code typed wrong, a seed that
    could not be written. The success side of all four was tested and the
    refusal side of none of them was, so a traceback in place of a
    sentence, or an exit 0 in place of a 1, would have gone out with the
    suite green.
    """

    def test_an_invalid_token_is_named_as_invalid(self, runner, app):
        """``validate-token`` is run to find out that a token is bad.

        The service answers ``None`` for one that is invalid or expired
        rather than raising, so the command has to say so itself -- and
        the sentence it says had never been printed.
        """
        result = runner.invoke(
            app.cli, ["security", "validate-token", "not-a-token"]
        )

        assert result.exit_code == 1
        assert "INVALID" in result.stderr, result.stderr
        assert "Traceback" not in result.output, result.output

    def test_a_token_the_service_could_not_read_reports_the_reason(
        self, runner, app
    ):
        """An exception on the way in is an answer, not a crash.

        Anything the library raises is caught and rendered as the reason
        the token was refused; without that the operator gets a traceback
        from a command whose whole job is to explain a token.
        """
        from link_shortener.infrastructure.cli.commands.security import (
            validate_token,
        )

        class Exploding:
            def validate_token(self, token):
                raise RuntimeError("key material is unreadable")

        answer = validate_token(Exploding(), "whatever")

        assert answer["valid"] is False
        assert "key material is unreadable" in answer["error"]

    def test_link_info_refuses_a_code_that_is_not_one(self, runner, app):
        """A malformed code is a refusal, not a ``ValueError``.

        ``ShortCode`` rejects it before any lookup happens, and the
        command turns that into the same "not found" it gives for a code
        nobody has taken -- which is the honest answer: there is no link
        with that code either way.
        """
        result = runner.invoke(app.cli, ["link", "info", "not a code!!"])

        assert result.exit_code == 1
        assert "not found" in result.stderr, result.stderr
        assert "Traceback" not in result.output, result.output

    def test_a_seeding_failure_is_reported_and_exits_one(self, runner, app):
        """``db seed`` writes through a use case, which can refuse."""
        container = app.container

        class Refusing:
            def execute(self, *args, **kwargs):
                raise RuntimeError("the database is read-only")

        real = container.get_seed_database_use_case
        container.get_seed_database_use_case = lambda: Refusing()
        try:
            result = runner.invoke(app.cli, ["db", "seed", "--count", "1"])
        finally:
            container.get_seed_database_use_case = real

        assert result.exit_code == 1
        assert "Seeding failed" in result.stderr, result.stderr
        assert "read-only" in result.stderr

    def test_a_link_that_cannot_be_created_is_reported_and_exits_one(
        self, runner, app
    ):
        """``link create`` refuses a URL the use case will not take."""
        result = runner.invoke(
            app.cli, ["link", "create", "--url", "not-a-url"]
        )

        assert result.exit_code == 1
        assert "Could not create the link" in result.stderr, result.stderr
        assert "Traceback" not in result.output, result.output


class TestTheListingsSayWhenThereIsNothing:
    """An empty table gets a sentence rather than a bare heading.

    Both listings print a header and then whatever rows there are, so
    without this they answered an empty database with column titles and
    nothing under them -- which reads as "the query failed" as easily as
    "there are none".
    """

    @pytest.fixture
    def app_on_an_empty_database(self, tmp_path):
        """An application whose database has the schema and nothing else."""
        from link_shortener.infrastructure.database.manager import (
            DatabaseManager,
        )
        from link_shortener.web.app_factory import create_app

        manager = DatabaseManager(
            database_url=f"sqlite:///{tmp_path / 'empty.db'}",
            echo=False,
            database_type="sqlite",
        )
        manager.connect()
        manager.create_tables()
        application = create_app(config=TestConfig())
        application.container.db_component._manager = manager
        yield application
        manager.close()

    def test_no_users(self, app_on_an_empty_database):
        runner = FlaskCliRunner(app_on_an_empty_database)

        result = runner.invoke(args=["security", "list-users"])

        assert result.exit_code == 0, result.output
        assert "No users found." in result.output

    def test_no_roles(self, app_on_an_empty_database):
        runner = FlaskCliRunner(app_on_an_empty_database)

        result = runner.invoke(args=["security", "list-roles"])

        assert result.exit_code == 0, result.output
        assert "No roles found." in result.output


class TestTheReportsWithSomethingInThem:
    """The other half again, the other way round.

    The refusals above were the untested half of four commands; these are
    the untested half of three more, and it is the ordinary one -- the
    listing that has rows, the statistics that have links, the cache that
    answers. Each was exercised only against an empty service, so the
    formatting every operator actually sees ran nowhere: the column
    widths, the clipping, and the heading that counts what is under it.
    """

    def test_the_statistics_head_the_list_with_what_is_in_it(
        self, runner, app
    ):
        """"TOP 5 POPULAR LINKS" was printed over however many there were.

        The heading counts the list now, so the two cannot disagree; only
        the empty branch had ever run.
        """
        class Stats:
            total_urls = 2
            total_clicks = 3
            avg_clicks_per_url = 1.5

            class _Link:
                def __init__(self, code, clicks):
                    self.short_code = code
                    self.clicks = clicks

            popular_links = [_Link("aaaaaa", 1), _Link("bbbbbb", 2)]

        real = app.container.get_get_service_stats_use_case
        app.container.get_get_service_stats_use_case = lambda: type(
            "UseCase", (), {"execute": staticmethod(lambda *a, **k: Stats())}
        )()
        try:
            result = runner.invoke(app.cli, ["stats", "show"])
        finally:
            app.container.get_get_service_stats_use_case = real

        assert result.exit_code == 0, result.output
        # Two links, so "2 POPULAR LINKS" -- not five, and not "1 LINKS".
        assert "TOP 2 POPULAR LINKS:" in result.output, result.output
        assert "1. aaaaaa - 1 click" in result.output
        assert "2. bbbbbb - 2 clicks" in result.output

    def test_the_cache_statistics_are_printed_when_the_cache_answers(
        self, runner, app
    ):
        """The table itself, which only the failing branch had exercised."""
        cache = MagicMock(spec=ServiceCache)
        cache.is_configured.return_value = True
        cache.get_cache_info.return_value = {"used_memory": "1.2M", "keys": 7}

        component = app.container.cache_component
        real = component._cache
        component._cache = cache
        try:
            result = runner.invoke(app.cli, ["cache", "stats"])
        finally:
            component._cache = real

        assert result.exit_code == 0, result.output
        assert "used_memory: 1.2M" in result.output
        assert "keys: 7" in result.output

    def test_the_user_listing_prints_a_row_per_account(self, runner, app):
        """Rows, with the address clipped to its column.

        ``_within`` both pads and clips, and a long address is what it
        exists for -- ``:<30`` alone left one wordy value pushing every
        column after it out of line.
        """
        long_address = "a-very-long-address-indeed@example.test"
        listing = [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "email": long_address,
                "is_active": True,
                "roles": ["admin", "user"],
            },
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "email": "short@example.test",
                "is_active": False,
                "roles": [],
            },
        ]
        import link_shortener.infrastructure.cli.adapters.flask as adapter

        real = adapter.list_users_logic
        adapter.list_users_logic = lambda *a, **k: listing
        try:
            result = runner.invoke(app.cli, ["security", "list-users"])
        finally:
            adapter.list_users_logic = real

        assert result.exit_code == 0, result.output
        assert "admin, user" in result.output
        # An account with no roles says so rather than showing a gap.
        assert "none" in result.output
        # Clipped to the column, ellipsis and all, rather than running on.
        assert long_address not in result.output, result.output
        assert "…" in result.output

class TestTheGuardsNobodyExpectsToTrip:
    """Three branches that exist so a mistake reads as a sentence.

    None had ever run. They are cheap to hold and the alternative to each
    is the thing they were written against: a traceback naming neither
    the object nor the missing call, a silent wrong answer, or an empty
    complaint.
    """

    def test_dropping_through_an_unconnected_manager_says_so(self):
        """``drop_db`` needs the engine ``connect()`` builds.

        Without the check, ``drop_all(bind=None)`` fails with a message
        naming neither the manager nor the call that was skipped.
        """
        from link_shortener.infrastructure.cli.commands.database import drop_db

        class Unconnected:
            engine = None

        with pytest.raises(RuntimeError, match="Call connect"):
            drop_db(Unconnected(), use_alembic=False)

    def test_a_database_answering_something_other_than_one_is_a_failure(self):
        """``SELECT 1`` returning anything else is not a healthy database.

        Reported as a reason rather than as ``None``, which would have
        been read as "healthy" by every caller.
        """
        from link_shortener.infrastructure.cli.commands.database import (
            check_db_connection,
        )

        class Odd:
            def session(self):
                class _Ctx:
                    def __enter__(ctx):
                        session = MagicMock()
                        session.execute.return_value.scalar.return_value = 0
                        return session

                    def __exit__(ctx, *exc):
                        return False

                return _Ctx()

        assert check_db_connection(Odd()) == (
            "the database did not answer SELECT 1 with 1"
        )

    def test_an_error_with_nothing_to_say_is_named_by_its_type(self):
        """An exception raised with no message still has to be reported.

        ``str(error)`` is empty, so the line an operator gets would be
        empty too -- the class name is the only thing left that says
        anything at all.
        """
        from link_shortener.infrastructure.cli.commands.maintenance import (
            what_the_database_said,
        )

        assert what_the_database_said(TimeoutError()) == "TimeoutError"


class TestEveryCommandInTheModuleIsReachable:
    """A command the module defines and the app never registers is invisible.

    ``register_flask_commands`` is the single door: a group written and
    not added there exists in the source, imports cleanly, and cannot be
    run. Nothing checked that door, so the omission would show up as an
    operator typing a documented command and being told there is no such
    command.

    Asserted by comparing what the module defines against what the
    application carries, rather than against a list of names typed out
    here -- a list would have to be edited for every command added, which
    is exactly the moment somebody is already editing two places and
    forgetting one.
    """

    def test_nothing_defined_is_left_unregistered(self, app):
        import click

        import link_shortener.infrastructure.cli.adapters.flask as adapter

        commands = [
            value
            for value in vars(adapter).values()
            if isinstance(value, click.Command)
        ]
        # Compared as objects rather than by name: ``stats`` is both a
        # group of its own and a subcommand of ``cache``, so a set of
        # names silently merges the two and the check stops meaning
        # anything.
        inside_a_group = {
            id(sub)
            for value in commands
            if isinstance(value, click.Group)
            for sub in value.commands.values()
        }
        top_level = [c for c in commands if id(c) not in inside_a_group]
        registered = {id(c) for c in app.cli.commands.values()}

        missing = [c.name for c in top_level if id(c) not in registered]
        assert missing == [], f"defined but not registered: {sorted(missing)}"

    def test_every_group_still_carries_its_commands(self, app):
        """The groups are registered with their subcommands attached.

        Registering the function instead of the group -- an easy slip,
        they sit one line apart -- gives a command that runs nothing.
        """
        import click

        for name, command in app.cli.commands.items():
            if isinstance(command, click.Group):
                assert command.commands, f"{name} has no subcommands"


class TestTheCountsAgreeWithTheirNouns:
    """One of a thing is not "1 things", and neither is it "1 addresss".

    The rule was already in the file -- ``_counted`` exists for it, and a
    commit put it into two of the reports. The other eight counted lines
    were left saying "Deleted 1 expired links", which is the sort of thing
    an operator reads once and stops trusting the tool over.

    Bringing them in widened what the helper is asked to pluralise, and
    the first word past ``click`` and ``link`` broke it: "address" came
    back as "addresss".
    """

    @pytest.mark.parametrize(
        "noun, one, many",
        [
            ("click", "1 click", "2 clicks"),
            ("expired link", "1 expired link", "2 expired links"),
            ("link-day", "1 link-day", "2 link-days"),
            # The sibilants, which take "es" and had been taking "s".
            ("address", "1 address", "2 addresses"),
            ("refresh session", "1 refresh session", "2 refresh sessions"),
            ("box", "1 box", "2 boxes"),
            ("batch", "1 batch", "2 batches"),
        ],
    )
    def test_the_plural_is_built_correctly(self, noun, one, many):
        from link_shortener.infrastructure.cli.adapters.flask import _counted

        assert _counted(1, noun) == one
        assert _counted(2, noun) == many

    def test_zero_takes_the_plural(self):
        """"0 links", not "0 link" -- the sweep that found nothing says so."""
        from link_shortener.infrastructure.cli.adapters.flask import _counted

        assert _counted(0, "expired link") == "0 expired links"

    def test_a_sweep_that_deleted_one_says_so_in_the_singular(
        self, runner, app
    ):
        """Through the command, not the helper: what is under test is that
        the reports were actually brought to the rule."""
        container = app.container

        class DeletedOne:
            def execute(self, context):
                return 1

        real = container.get_clean_expired_links_use_case
        container.get_clean_expired_links_use_case = lambda: DeletedOne()
        try:
            result = runner.invoke(app.cli, ["maintenance", "clean-expired"])
        finally:
            container.get_clean_expired_links_use_case = real

        assert "Deleted 1 expired link." in result.output, result.output


class TestBothStatsCommandsPrintOneReport:
    """The same three figures, printed by one block rather than two.

    ``stats show`` and ``stats refresh`` report the same numbers off the
    same response and had drifted into two layouts -- one aligned its
    labels, the other did not; one wrote "Total URLs" and the other
    "Total URL's", which is a possessive and not a plural.
    """

    @staticmethod
    def _standing_in_for_the_use_case(app, totals):
        """Hand both commands the same fixed answer."""
        class Stats:
            total_urls = totals
            total_clicks = 4
            avg_clicks_per_url = 2.0
            popular_links = []

        return lambda: type(
            "UseCase", (), {"execute": staticmethod(lambda *a, **k: Stats())}
        )()

    def test_the_two_reports_carry_the_same_lines(self, runner, app):
        real = app.container.get_get_service_stats_use_case
        app.container.get_get_service_stats_use_case = (
            self._standing_in_for_the_use_case(app, 2)
        )
        try:
            shown = runner.invoke(app.cli, ["stats", "show"]).output
            refreshed = runner.invoke(app.cli, ["stats", "refresh"]).output
        finally:
            app.container.get_get_service_stats_use_case = real

        figures = [
            "Total URLs:      2",
            "Total clicks:    4",
            "Avg clicks/URL:  2.0",
        ]
        for line in figures:
            assert line in shown, shown
            assert line in refreshed, refreshed

    def test_neither_writes_the_plural_as_a_possessive(self, runner, app):
        real = app.container.get_get_service_stats_use_case
        app.container.get_get_service_stats_use_case = (
            self._standing_in_for_the_use_case(app, 2)
        )
        try:
            both = (
                runner.invoke(app.cli, ["stats", "show"]).output
                + runner.invoke(app.cli, ["stats", "refresh"]).output
            )
        finally:
            app.container.get_get_service_stats_use_case = real

        assert "URL's" not in both, both


class TestRefusalsAreWrittenTheSameWay:
    """One shape for a refusal, across the whole of the CLI.

    Six of the twenty-four wrote a prefix -- ``ERROR:`` four times,
    ``Error:`` once, ``Error creating link:`` once -- and the other
    eighteen wrote a sentence. On stderr the prefix says nothing the
    stream has not said already, and three spellings of it are worse than
    none: a script grepping for ``ERROR`` finds a quarter of the
    refusals and reads the rest as success.
    """

    def test_no_refusal_carries_a_prefix(self):
        import re

        import link_shortener.infrastructure.cli.adapters.flask as adapter

        source = pathlib.Path(adapter.__file__).read_text()
        # Every echo that goes to the error stream, with its opening text.
        refusals = re.findall(
            r"click\.echo\(\s*(f?\"(?:[^\"\\\\]|\\\\.)*\")[^)]*err=True",
            source,
        )
        assert refusals, "the scan found nothing, so it proves nothing"

        prefixed = [
            text for text in refusals
            if re.match(r'f?"(ERROR|Error)\b', text)
        ]
        assert prefixed == [], prefixed

    def test_no_command_refuses_through_click_s_own_exception(self):
        """``ClickException`` writes the prefix this file does not use.

        It renders as ``Error: <message>`` regardless of what the module
        does, so one command kept the shape after every literal had been
        brought into line -- and the scan above could not see it, because
        there is no string to find.
        """
        import link_shortener.infrastructure.cli.adapters.flask as adapter

        source = pathlib.Path(adapter.__file__).read_text()

        # The call, not the word: the comment explaining why it is not
        # used names it, and a scan for the name alone would forbid
        # writing that explanation down.
        raised = re.findall(r"raise\s+click\.ClickException", source)

        assert raised == [], (
            "a refusal is echoed to stderr and exits 1, like the others"
        )

    def test_a_missing_env_file_is_refused_without_a_prefix(self, runner, app):
        """The one that had it, measured through the command."""
        result = runner.invoke(
            app.cli,
            ["security", "generate-secrets", "--write", "/nowhere/absent.env"],
        )

        assert result.exit_code == 1
        assert result.stderr.startswith("/nowhere/absent.env"), result.stderr
        assert "Error" not in result.stderr, result.stderr


class TestARefusalIsNotDressedAsAReport:
    """A refused command leaves nothing but the sentence saying why.

    ``link delete`` and ``link info`` printed their rules of ``=`` around
    the refusal too, and the refusal itself goes to stderr -- so a run
    whose output was redirected kept two rules with nothing between them,
    and the reason was in the stream nobody kept.
    """

    @pytest.mark.parametrize(
        "argv", [["link", "delete", "nolink123"], ["link", "info", "nolink123"]]
    )
    def test_stdout_is_empty_when_the_link_is_not_there(self, runner, app, argv):
        result = runner.invoke(app.cli, argv)

        assert result.exit_code == 1
        assert result.stdout.strip() == "", result.stdout
        assert "not found" in result.stderr, result.stderr

    def test_a_report_still_has_its_frame(self, runner, app):
        """The rules were not removed, only moved off the refusal."""
        runner.invoke(
            app.cli, ["link", "create", "--url", "https://example.com/framed",
                      "--code", "framed"]
        )

        result = runner.invoke(app.cli, ["link", "info", "framed"])

        assert result.exit_code == 0, result.output
        assert result.stdout.count("=" * 80) == 2, result.stdout


class TestACountThatMakesNoSenseIsRefused:
    """Zero and below are refused rather than answered.

    ``--count "$N"`` with the variable unset or miscomputed is the way
    this arrives, and it used to be answered with "Created 0 test links"
    and exit 0 -- a script reading that has been told its seeding
    worked. The same reasoning already refuses an empty ``--code`` a few
    commands along.

    Enforced by Click's own range rather than checked in the body, so the
    message names the bound and the command never runs.
    """

    @pytest.mark.parametrize(
        "argv",
        [
            ["db", "seed", "--count", "0"],
            ["db", "seed", "--count", "-3"],
            ["link", "list", "--limit", "0"],
            ["link", "list", "--limit", "-5"],
        ],
    )
    def test_it_is_refused_before_anything_runs(self, runner, app, argv):
        result = runner.invoke(app.cli, argv)

        # 2 is Click's own code for a bad invocation, and it is the right
        # one: nothing about the service is wrong.
        assert result.exit_code == 2, result.output
        assert "is not in the range" in result.output, result.output

    def test_a_sensible_count_still_works(self, runner, app):
        """The bound is at one, not above it."""
        result = runner.invoke(app.cli, ["link", "list", "--limit", "1"])

        assert result.exit_code == 0, result.output


class TestAnEmptyRevisionIsRefused:
    """``--revision ""`` is an unfilled variable, not a request for all.

    Read as falsy, it listed the whole history and exited 0, so a script
    asking for the history from one revision was handed every revision
    and told it had succeeded. ``--code ""`` was refused for this exact
    reason a slice earlier; this is the same shape in another command.
    """

    def test_an_empty_revision_stops_the_command(self, runner, app):
        result = runner.invoke(
            app.cli, ["alembic", "history", "--revision", ""]
        )

        assert result.exit_code == 1
        assert "empty value" in result.stderr, result.stderr
        # Not a listing: nothing of the history reached the operator.
        assert "->" not in result.stdout, result.stdout

    def test_leaving_it_out_still_shows_everything(self, runner, app):
        """The reading the empty value was being taken for."""
        result = runner.invoke(app.cli, ["alembic", "history"])

        assert result.exit_code == 0, result.output

    def test_a_range_that_was_given_is_still_used(self, runner, app):
        """Blank-only values are refused; a real range goes through.

        A range, not a bare revision: alembic answers "History range
        requires [start]:[end], [start]:, or :[end]" to ``-r 0001`` --
        measured -- and the option's help had been promising exactly the
        form that does not work.
        """
        result = runner.invoke(
            app.cli, ["alembic", "history", "--revision", "0001:"]
        )

        assert result.exit_code == 0, result.output

    def test_the_help_names_a_range_rather_than_a_revision(self, runner, app):
        """What the option says it takes is what alembic takes."""
        result = runner.invoke(app.cli, ["alembic", "history", "--help"])

        assert "range" in result.output, result.output
        assert "0001:" in result.output, result.output


class TestWritingSecretsIntoAFileThatWillNotTakeThem:
    """The command answers, rather than letting the failure through.

    ``--write`` is the step a setup guide tells an operator to run, and
    the file it names is often one they do not own yet. That arrived as a
    ``PermissionError`` with nothing on stderr -- the one refusal in the
    CLI that was not a sentence.
    """

    def test_a_file_that_cannot_be_written_is_refused_with_a_reason(
        self, runner, app, tmp_path
    ):
        import os

        locked = tmp_path / "locked.env"
        locked.write_text("SECRET_KEY=\n", encoding="utf-8")
        os.chmod(locked, 0o444)
        try:
            result = runner.invoke(
                app.cli,
                ["security", "generate-secrets", "--write", str(locked)],
            )
        finally:
            os.chmod(locked, 0o644)

        assert result.exit_code == 1
        assert result.exception is None or isinstance(
            result.exception, SystemExit
        ), result.exception
        assert "Permission denied" in result.stderr, result.stderr
        # And the values are not printed as a consolation: a secret that
        # was meant for a file has no reason to reach the scrollback.
        assert "SECRET_KEY=" not in result.stdout, result.stdout

    def test_a_directory_is_refused_as_a_directory(
        self, runner, app, tmp_path
    ):
        result = runner.invoke(
            app.cli, ["security", "generate-secrets", "--write", str(tmp_path)]
        )

        assert result.exit_code == 1
        assert "is not a file" in result.stderr, result.stderr


class TestTheThreeListingsAnswerEmptinessAlike:
    """"Nothing here" is one sentence, in all three places.

    ``link list`` ruled a line of ``=`` above and below its one sentence
    while ``security list-users`` and ``list-roles`` printed theirs bare
    -- and a lone sentence between two rules reads as a table that failed
    to print rather than as an empty one.
    """

    @pytest.fixture
    def app_on_an_empty_database(self, tmp_path):
        from link_shortener.infrastructure.database.manager import (
            DatabaseManager,
        )
        from link_shortener.web.app_factory import create_app

        manager = DatabaseManager(
            database_url=f"sqlite:///{tmp_path / 'bare.db'}",
            echo=False,
            database_type="sqlite",
        )
        manager.connect()
        manager.create_tables()
        application = create_app(config=TestConfig())
        application.container.db_component._manager = manager
        yield application
        manager.close()

    @pytest.mark.parametrize(
        "argv, sentence",
        [
            (["link", "list"], "No links found."),
            (["security", "list-users"], "No users found."),
            (["security", "list-roles"], "No roles found."),
        ],
    )
    def test_it_is_one_bare_sentence(self, app_on_an_empty_database, argv, sentence):
        runner = FlaskCliRunner(app_on_an_empty_database)

        result = runner.invoke(args=argv)

        assert result.exit_code == 0, result.output
        assert result.stdout.strip() == sentence, result.stdout

    def test_a_listing_with_rows_still_has_its_frame(self, runner, app):
        """The rules were not removed, only kept off the empty answer."""
        runner.invoke(
            app.cli,
            ["link", "create", "--url", "https://example.com/listed",
             "--code", "listed"],
        )

        result = runner.invoke(app.cli, ["link", "list"])

        assert result.exit_code == 0, result.output
        assert result.stdout.count("=" * 80) == 2, result.stdout


class TestOneMomentFormat:
    """A moment looks the same whichever command states it.

    ``security validate-token`` rendered a JWT ``exp`` through
    ``UTC_SECONDS`` while ``link info`` printed a stored datetime through
    ``isoformat()`` -- so the same kind of fact came out in two forms, one
    of them carrying microseconds and a numeric offset.
    """

    def test_an_epoch_and_a_datetime_are_written_alike(self):
        from datetime import datetime, timezone

        from link_shortener.infrastructure.cli.adapters.flask import _as_moment

        moment = datetime(2026, 8, 22, 15, 4, 5, 123456, tzinfo=timezone.utc)

        assert _as_moment(moment) == "2026-08-22T15:04:05Z"
        assert _as_moment(int(moment.timestamp())) == "2026-08-22T15:04:05Z"

    def test_a_moment_in_another_zone_is_stated_in_utc(self):
        """The zone travels with the value; the report does not."""
        from datetime import datetime, timedelta, timezone

        from link_shortener.infrastructure.cli.adapters.flask import _as_moment

        elsewhere = timezone(timedelta(hours=3))
        moment = datetime(2026, 8, 22, 18, 4, 5, tzinfo=elsewhere)

        assert _as_moment(moment) == "2026-08-22T15:04:05Z"

    def test_nothing_to_state_is_said_as_unknown(self):
        from link_shortener.infrastructure.cli.adapters.flask import _as_moment

        assert _as_moment(None) == "unknown"

    def test_link_info_states_its_moments_the_same_way(self, runner, app):
        """Through the command, so the helper is not the only witness."""
        import re

        runner.invoke(
            app.cli,
            ["link", "create", "--url", "https://example.com/moment",
             "--code", "moment"],
        )

        result = runner.invoke(app.cli, ["link", "info", "moment"])

        assert result.exit_code == 0, result.output
        assert re.search(
            r"Created: \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
            result.output,
            re.M,
        ), result.output


class TestAFailureToReportIsNotAFailureToCreate:
    """The clause covers the creation and nothing after it.

    ``link create`` wrapped its whole body, report included, so anything
    raised while printing came out as "Could not create the link", exit
    1, for a link that existed and whose code the operator then never
    saw. ``CreateUserUseCase`` states the same rule for the same reason.
    """

    def test_a_report_that_fails_is_not_called_a_failed_creation(
        self, runner, app, monkeypatch
    ):
        import link_shortener.infrastructure.cli.adapters.flask as adapter

        class ReportBreaksHalfway:
            """A response that answers, then stops answering.

            What the report reads after the code -- printing is where the
            failure lands, and the creation is already done by then.
            """

            is_new = True
            short_code = "halfway"
            original_url = "https://example.com/halfway"

            @property
            def short_url(self):
                raise BrokenPipeError("stdout is gone")

        monkeypatch.setattr(
            adapter, "create_link_logic",
            lambda *a, **k: ReportBreaksHalfway(),
        )

        result = runner.invoke(
            app.cli,
            ["link", "create", "--url", "https://example.com/halfway"],
        )

        # Whatever the failure does, it is not announced as the creation
        # having failed -- that sentence is reserved for the use case.
        assert "Could not create the link" not in (result.stderr or ""), (
            result.stderr
        )
        # And what was already printed stays printed: the code reached
        # the operator.
        assert "halfway" in result.stdout, result.stdout
