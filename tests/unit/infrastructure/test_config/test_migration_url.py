"""
What a migration demands before it runs, and what it refuses to run against.

``alembic upgrade head`` connects with one string and reads nothing else
the application knows. Obtaining it must not mean building *and
validating* the whole configuration: under ``production`` with
``DATABASE_URL`` already set, that refuses four times over --
``SECRET_KEY``, ``SHORT_CODE_PEPPER``, ``REDIS_URL``, ``DOMAIN`` -- before
creating a single table, and a mail server or an over-long
``MAX_URL_LENGTH`` stopped it just as well. None of those reach a
migration.

The counterweight is the last check in ``resolve_database_url``. Dropping
the validation also drops the accidental guard it provided: with nothing
configured, ``DATABASE_TYPE`` defaults to SQLite and ``DATABASE_NAME`` to
``db_shortener``, so a deployment that forgot its settings gets a
migration that succeeds against a new empty file and a service that then
starts on it.

The tests that claim something is *no longer* demanded pin the refusal
they are the counterpart to: without ``create_config()`` raising in the
same environment, "the URL came back" would also pass on a configuration
that was valid all along.
"""

import pytest

from link_shortener.infrastructure.configs.app.base import BaseConfig
from link_shortener.infrastructure.configs.app.factory import ConfigFactory
from link_shortener.infrastructure.configs.app.migration_url import (
    HANDOFF_ENV_VAR, migration_connect_args, resolve_database_url
)
from link_shortener.infrastructure.database.manager import DatabaseManager


# Variables that decide which database is opened. Cleared before each test
# so the developer's own shell cannot supply one the test never set.
DATABASE_VARS = (
    HANDOFF_ENV_VAR,
    "FLASK_ENV",
    "DATABASE_URL",
    "DATABASE_TYPE",
    "DATABASE_NAME",
    "DATABASE_USER",
    "DATABASE_PASSWORD",
    "DATABASE_HOST",
    "DATABASE_PORT",
    "DATABASE_CONNECT_TIMEOUT",
    "DATABASE_STATEMENT_TIMEOUT",
    "MAX_URL_LENGTH",
    "MAIL_ENABLED",
    "DOMAIN",
    "SECRET_KEY",
    "SHORT_CODE_PEPPER",
)


@pytest.fixture(autouse=True)
def only_what_the_test_sets(monkeypatch):
    """
    Detach the resolution from this machine.

    Both halves matter. The environment is cleared because the suite runs
    where a developer keeps a real ``DATABASE_URL`` exported, and the
    ``.env`` lookup is stubbed because the repository the tests run from
    has one -- with ``FLASK_ENV=development`` in it, which is the single
    profile these refusals do not apply to.
    """
    monkeypatch.setattr(
        ConfigFactory, "_read_env_file", staticmethod(lambda filename: {})
    )
    for name in DATABASE_VARS:
        monkeypatch.delenv(name, raising=False)


class TestTheCallerHandoff:
    """A URL handed over by the caller is used exactly as given."""

    def test_the_handed_over_url_wins_over_the_configuration(self, monkeypatch):
        monkeypatch.setenv("FLASK_ENV", "development")
        monkeypatch.setenv(HANDOFF_ENV_VAR, "postgresql+psycopg://u:p@h/db")

        assert resolve_database_url() == "postgresql+psycopg://u:p@h/db"

    def test_a_trailing_newline_is_stripped(self, monkeypatch):
        """A URL ending in a newline names a *different* database.

        Without the strip it creates a SQLite file whose name ends in
        "\\n", beside the one that was meant.
        """
        monkeypatch.setenv(HANDOFF_ENV_VAR, "sqlite:///wanted.db\n")

        assert resolve_database_url() == "sqlite:///wanted.db"

    def test_a_blank_handoff_falls_through_to_the_configuration(
        self, monkeypatch
    ):
        """``docker compose`` substitutes a blank for every missing ``${VAR}``.

        Taken literally, the migration would be handed an empty URL and
        fail on it instead of resolving one.
        """
        monkeypatch.setenv("FLASK_ENV", "development")
        monkeypatch.setenv(HANDOFF_ENV_VAR, "   ")
        monkeypatch.setenv("DATABASE_URL", "sqlite:///from-config.db")

        assert resolve_database_url() == "sqlite:///from-config.db"


class TestWhatIsNoLongerDemanded:
    """Settings a migration never reads no longer stop one."""

    def test_a_configuration_the_application_could_not_start_on_still_migrates(
        self, monkeypatch
    ):
        """The whole point, and the regression that would undo it.

        ``MAX_URL_LENGTH`` is the sharpest example available: a limit on
        the length of a submitted link, refused at startup above 2048, and
        entirely unrelated to connecting to a database. The mail settings
        are here because they were measured stopping a migration too.
        """
        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv(
            "DATABASE_URL", "postgresql+psycopg://u:p@db.internal:5432/short"
        )
        monkeypatch.setenv("MAX_URL_LENGTH", "99999")
        monkeypatch.setenv("MAIL_ENABLED", "true")

        # Independent evidence that this environment is genuinely broken.
        # Without it, the assertion below would also pass on a
        # configuration that had nothing wrong with it.
        with pytest.raises(ValueError):
            ConfigFactory.create_config()

        assert resolve_database_url() == (
            "postgresql+psycopg://u:p@db.internal:5432/short"
        )

    def test_the_missing_secrets_of_a_production_profile_do_not_stop_one(
        self, monkeypatch
    ):
        """``SECRET_KEY`` signs tokens; a migration issues none."""
        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv("DATABASE_URL", "sqlite:///named.db")

        with pytest.raises(ValueError, match="SECRET_KEY"):
            ConfigFactory.create_config()

        assert resolve_database_url() == "sqlite:///named.db"


class TestWhatIsStillChecked:
    """What a bad connection setting still costs, and where it is caught.

    Only the first two of these are held by ``validate_database``. The
    other two are refused by ``get_database_url`` on its way to building a
    URL and would be refused with no validation at all -- measured by
    removing the ``validate_database()`` call, which left them green. They
    are kept for the behaviour, not as evidence that the check runs.
    """

    def test_connection_options_smuggled_into_the_name_are_refused(
        self, monkeypatch
    ):
        """``shortener?sslmode=disable`` connects, and connects in the clear.

        The setting still reads like a plain name, which is why this one
        is worth keeping when the rest of the validation is skipped. This
        is one of the two that nothing else would catch.
        """
        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv("DATABASE_TYPE", "postgresql")
        monkeypatch.setenv("DATABASE_NAME", "shortener?sslmode=disable")
        monkeypatch.setenv("DATABASE_USER", "u")
        monkeypatch.setenv("DATABASE_PASSWORD", "p")
        monkeypatch.setenv("DATABASE_HOST", "db.internal")

        with pytest.raises(ValueError, match="DATABASE_NAME must not contain"):
            resolve_database_url()

    def test_the_same_options_smuggled_into_the_host_are_refused(
        self, monkeypatch
    ):
        """The host was the hole the name check left open.

        ``URL.create`` percent-encodes the user and the password but not
        the host, so this one arrives whole: measured as host
        ``db.internal``, database ``shortener`` and ``sslmode=disable``,
        with the ``DATABASE_NAME`` and ``DATABASE_PORT`` that say
        otherwise dropped without a word.
        """
        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv("DATABASE_TYPE", "postgresql")
        monkeypatch.setenv("DATABASE_NAME", "shortener")
        monkeypatch.setenv("DATABASE_USER", "u")
        monkeypatch.setenv("DATABASE_PASSWORD", "p")
        monkeypatch.setenv(
            "DATABASE_HOST", "db.internal/other?sslmode=disable"
        )

        with pytest.raises(ValueError, match="DATABASE_HOST must not contain"):
            resolve_database_url()

    def test_a_database_type_nothing_can_open_is_refused(self, monkeypatch):
        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv("DATABASE_TYPE", "mysql")

        with pytest.raises(ValueError, match="Unsupported DATABASE_TYPE"):
            resolve_database_url()

    def test_an_incomplete_postgresql_setting_is_still_refused(
        self, monkeypatch
    ):
        """The parts are missing, so there is no URL to return at all."""
        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv("DATABASE_TYPE", "postgresql")

        with pytest.raises(ValueError, match="PostgreSQL connection requires"):
            resolve_database_url()


class TestWhatIsNoLongerChecked:
    """Settings that stop being read once the URL is written out in full."""

    def test_a_stale_database_type_does_not_stop_a_named_database(
        self, monkeypatch
    ):
        """``get_database_url`` returns ``DATABASE_URL`` before reading it.

        Refusing anyway stopped a migration over a value that changes
        nothing, on the recovery path this whole module exists to keep
        open, with a message naming the wrong setting. The application's
        own ``validate()`` still refuses it -- pinned here, because
        otherwise this test would also pass if the check had been deleted
        outright.
        """
        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv("DATABASE_URL", "sqlite:///named.db")
        monkeypatch.setenv("DATABASE_TYPE", "mysql")
        # Everything else a production profile demands, so that the pin
        # below fails on the database setting and not on the first missing
        # secret it happens to reach.
        monkeypatch.setenv("SECRET_KEY", "k")
        monkeypatch.setenv("SHORT_CODE_PEPPER", "p")
        monkeypatch.setenv("DOMAIN", "example.test")
        monkeypatch.setenv("REDIS_ENABLED", "false")

        with pytest.raises(ValueError, match="Unsupported DATABASE_TYPE"):
            ConfigFactory.create_config()

        assert resolve_database_url() == "sqlite:///named.db"

    def test_a_url_with_a_trailing_newline_names_the_same_file_on_both_sides(
        self, monkeypatch
    ):
        """Both sides strip, and both must name the same file.

        With only the handoff stripped, ``flask alembic upgrade``
        migrated ``app.db`` while the application it was launched from
        opened ``app.db\\n`` -- two files, one of them empty, no error on
        either side. A URL read out of a file or a k8s Secret is exactly
        how the newline arrives.
        """
        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv("DATABASE_URL", "sqlite:////tmp/app.db\n")

        application = ConfigFactory.create_config_unvalidated(
            "production"
        ).get_database_url()

        assert resolve_database_url() == application
        assert application == "sqlite:////tmp/app.db"


class TestHowLongAMigrationWaits:
    """The bounds the application connects under, applied to a migration."""

    def test_a_migration_connects_under_the_configured_bounds(
        self, monkeypatch
    ):
        """Without the bounds: 60 seconds and counting against an
        unreachable server, where the application gives up in 3.6.

        The migration builds its own engine from the ``[alembic]`` section,
        which holds nothing but the URL, so nothing bounded the wait -- and
        ``app`` starts only once that command has finished.
        """
        monkeypatch.setenv("DATABASE_CONNECT_TIMEOUT", "4")
        monkeypatch.setenv("DATABASE_STATEMENT_TIMEOUT", "7")

        args = migration_connect_args("postgresql+psycopg://u:p@h:5432/db")

        assert args["connect_timeout"] == 4
        assert args["options"] == "-c statement_timeout=7000"

    def test_sqlite_is_given_none_of_them(self):
        """These are libpq settings; SQLite would refuse them outright."""
        assert migration_connect_args("sqlite:////tmp/app.db") == {}

    def test_they_are_the_arguments_the_application_uses(self, monkeypatch):
        """Built by the same function, and held to it.

        Two copies of this mapping is how a migration ends up connecting
        under bounds nobody changed on purpose -- so the assertion is
        against ``DatabaseManager`` itself rather than against a literal
        repeated from it.
        """
        monkeypatch.setenv("DATABASE_CONNECT_TIMEOUT", "4")
        monkeypatch.setenv("DATABASE_STATEMENT_TIMEOUT", "7")

        application = DatabaseManager(
            "postgresql+psycopg://u:p@h:5432/db",
            echo=False,
            database_type="postgresql",
            connect_timeout=4,
            statement_timeout=7,
        )._connect_args()

        assert migration_connect_args(
            "postgresql+psycopg://u:p@h:5432/db"
        ) == application["connect_args"]


class TestADatabaseNobodyNamed:
    """The guard that replaces the one the dropped validation provided."""

    def test_a_production_profile_with_nothing_configured_is_refused(
        self, monkeypatch
    ):
        """The failure that has no symptom.

        SQLite creates a missing file rather than refusing it, so this
        migration would report success, and the service would come up on
        an empty database as if nothing had ever been stored.
        """
        monkeypatch.setenv("FLASK_ENV", "production")

        with pytest.raises(ValueError, match="no DATABASE_URL in the env"):
            resolve_database_url()

    def test_a_staging_profile_with_nothing_configured_is_refused_too(
        self, monkeypatch
    ):
        """Staging says of itself that it mirrors production."""
        monkeypatch.setenv("FLASK_ENV", "staging")

        with pytest.raises(ValueError, match="no DATABASE_URL in the env"):
            resolve_database_url()

    def test_a_profile_nobody_named_is_refused_rather_than_defaulted(
        self, monkeypatch
    ):
        """An unnamed profile is a refusal, not a default.

        ``DEFAULT_ENV`` is ``development``, which is also the one profile
        allowed a default database -- so on a host that sets ``FLASK_ENV``
        nowhere and has no ``.env`` (the settings arrive from systemd or
        from the orchestrator), the guard resolved itself out of existence
        and the migration creates ``db_shortener`` under ``DATABASE_DIR``:
        147456 bytes and exit 0.
        """
        with pytest.raises(ValueError, match="nothing names a profile"):
            resolve_database_url()

    def test_a_profile_named_only_in_the_env_file_still_counts(
        self, monkeypatch
    ):
        """``.env`` is the documented place to put ``FLASK_ENV``.

        Refusing here would break the documented local setup, where the
        file is the only thing that names the profile.
        """
        monkeypatch.setattr(
            ConfigFactory,
            "_read_env_file",
            staticmethod(lambda filename: {"FLASK_ENV": "development"}),
        )

        assert resolve_database_url().startswith("sqlite:///")

    def test_a_sqlite_database_named_in_the_environment_is_allowed(
        self, monkeypatch
    ):
        """Outside development, SQLite may only be asked for by URL.

        Not "the default is refused": a fully explicit ``DATABASE_TYPE``
        and ``DATABASE_NAME`` are refused too, because neither is read
        once ``DATABASE_URL`` decides. Writing the file down in the URL is
        the whole of the difference.
        """
        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv("DATABASE_URL", "sqlite:////var/lib/app/short.db")

        assert resolve_database_url() == "sqlite:////var/lib/app/short.db"

    def test_an_explicit_sqlite_name_without_a_url_is_refused(
        self, monkeypatch
    ):
        """The other half of the sentence above, held to it.

        An operator who sets ``DATABASE_TYPE=sqlite`` and a real path is
        being deliberate, and is still refused -- so the docstrings must
        not claim only defaults are caught.
        """
        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv("DATABASE_TYPE", "sqlite")
        monkeypatch.setenv("DATABASE_NAME", "/var/lib/app/short.db")

        with pytest.raises(ValueError, match="no DATABASE_URL in the env"):
            resolve_database_url()

    def test_a_postgresql_server_built_from_its_parts_is_allowed(
        self, monkeypatch
    ):
        """No ``DATABASE_URL`` here, and nothing to refuse: it is not SQLite.

        This is the shape the docker stack runs in, so a guard that
        demanded ``DATABASE_URL`` outright would stop it.
        """
        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv("DATABASE_TYPE", "postgresql")
        monkeypatch.setenv("DATABASE_USER", "shortener")
        monkeypatch.setenv("DATABASE_PASSWORD", "secret")
        monkeypatch.setenv("DATABASE_HOST", "db")
        monkeypatch.setenv("DATABASE_NAME", "db_shortener")

        assert resolve_database_url() == (
            "postgresql+psycopg://shortener:secret@db:5432/db_shortener"
        )

    def test_development_may_still_migrate_its_default_file(self, monkeypatch):
        """The local setup of the quick start, on a fresh clone.

        The quick start's own third command is ``flask alembic upgrade
        head``, which hands
        the URL over and never reaches any of this; the bare form of the
        same command does, and the file the profile falls back to is
        exactly the one the developer wants.
        """
        monkeypatch.setenv("FLASK_ENV", "development")

        assert resolve_database_url().startswith("sqlite:///")


class TestADatabaseThatDoesNotOutliveTheCommand:
    """In-memory: the migration that succeeds and leaves nothing behind."""

    @pytest.mark.parametrize(
        "url", ["sqlite://", "sqlite:///", "sqlite:///:memory:"]
    )
    def test_an_in_memory_url_is_refused_however_it_is_spelled(
        self, monkeypatch, url
    ):
        """One character from ``sqlite:///path``, and no way to tell.

        Without the check ``alembic upgrade head`` prints
        ``Running upgrade -> 0001`` and exits 0, having built the schema in
        a database that ceases to exist as the process ends.
        """
        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv("DATABASE_URL", url)

        with pytest.raises(ValueError, match="only inside this process"):
            resolve_database_url()

    def test_the_testing_profile_is_refused_and_told_the_only_way_out(
        self, monkeypatch
    ):
        """The profile pins one, and cannot be argued out of it.

        ``IGNORE_ENV`` means ``DATABASE_URL`` is not read at all, so
        telling this operator to set it would send them round the same
        refusal a second time -- the remedy has to name the handoff
        instead.
        """
        monkeypatch.setenv("FLASK_ENV", "testing")

        with pytest.raises(ValueError) as refusal:
            resolve_database_url()

        message = str(refusal.value)
        assert "only inside this process" in message
        assert HANDOFF_ENV_VAR in message
        assert "takes no configuration from the environment" in message

    def test_a_detached_profile_is_not_talked_out_of_it_by_the_environment(
        self, monkeypatch
    ):
        """The question has to be the one the configuration answers.

        Asked of ``os.environ`` instead, an exported ``DATABASE_URL``
        looks like a deliberate choice and waves the migration through --
        to the file this profile pins, not to the server the variable
        names, and with nothing to report the difference.

        A profile is built here rather than borrowed: ``testing`` is
        detached too, but it pins an in-memory database and is refused one
        step earlier, so it cannot tell these two readings apart.
        """
        pinned = type(
            "PinnedConfig",
            (BaseConfig,),
            {"IGNORE_ENV": True, "DATABASE_URL": "sqlite:///pinned.db"},
        )
        monkeypatch.setitem(ConfigFactory.CONFIG_MAP, "pinned", pinned)
        monkeypatch.setenv("FLASK_ENV", "pinned")
        monkeypatch.setenv(
            "DATABASE_URL", "postgresql+psycopg://u:p@db.internal:5432/short"
        )

        with pytest.raises(ValueError, match="no DATABASE_URL in the env"):
            resolve_database_url()


class TestAPostgresqlDatabaseNobodyNamed:
    """The SQLite default has an equivalent on the other backend.

    ``DATABASE_HOST`` defaults to ``localhost`` and ``DATABASE_NAME`` to
    ``db_shortener``, so a deployed profile that set only
    ``DATABASE_TYPE=postgresql`` and a user builds a valid URL to a server
    and a database nobody chose. The application refuses exactly that --
    and the migration did not: measured under ``staging``,
    ``resolve_database_url`` handed back
    ``postgresql+psycopg://shortener@localhost:5432/db_shortener`` while
    the service that would use it refused to start, naming a different
    setting.
    """

    @pytest.mark.parametrize("profile", ["staging", "production"])
    @pytest.mark.parametrize("missing", ["DATABASE_HOST", "DATABASE_NAME"])
    def test_a_defaulted_part_stops_the_migration(
        self, monkeypatch, profile, missing
    ):
        monkeypatch.setenv("FLASK_ENV", profile)
        monkeypatch.setenv("DATABASE_TYPE", "postgresql")
        monkeypatch.setenv("DATABASE_USER", "shortener")
        for name, value in (
            ("DATABASE_HOST", "db.internal"),
            ("DATABASE_NAME", "shortener"),
        ):
            if name == missing:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)

        with pytest.raises(ValueError, match="nobody named"):
            resolve_database_url()

    def test_named_parts_are_migrated(self, monkeypatch):
        """The other half: this must not stop a configured deployment."""
        monkeypatch.setenv("FLASK_ENV", "staging")
        monkeypatch.setenv("DATABASE_TYPE", "postgresql")
        monkeypatch.setenv("DATABASE_USER", "shortener")
        monkeypatch.setenv("DATABASE_HOST", "db.internal")
        monkeypatch.setenv("DATABASE_NAME", "shortener")

        url = resolve_database_url()

        assert "db.internal" in url
        assert "shortener" in url

    def test_localhost_is_allowed_when_somebody_says_it(self, monkeypatch):
        """A database on the same host is a real deployment.

        The difference between this and the case above is that somebody
        wrote the value, which is what the check asks.
        """
        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv("DATABASE_TYPE", "postgresql")
        monkeypatch.setenv("DATABASE_USER", "shortener")
        monkeypatch.setenv("DATABASE_HOST", "localhost")
        monkeypatch.setenv("DATABASE_NAME", "db_shortener")

        assert "localhost" in resolve_database_url()

    def test_a_whole_url_is_not_second_guessed(self, monkeypatch):
        """The parts are not read at all once ``DATABASE_URL`` is set."""
        monkeypatch.setenv("FLASK_ENV", "staging")
        monkeypatch.setenv(
            "DATABASE_URL", "postgresql+psycopg://u:p@elsewhere/short"
        )
        monkeypatch.delenv("DATABASE_HOST", raising=False)
        monkeypatch.delenv("DATABASE_NAME", raising=False)

        assert "elsewhere" in resolve_database_url()

    def test_development_still_migrates_what_it_finds(self, monkeypatch):
        """The local profile is the one allowed a database nobody named."""
        monkeypatch.setenv("FLASK_ENV", "development")
        monkeypatch.setenv("DATABASE_TYPE", "postgresql")
        monkeypatch.setenv("DATABASE_USER", "shortener")
        monkeypatch.delenv("DATABASE_HOST", raising=False)
        monkeypatch.delenv("DATABASE_NAME", raising=False)

        assert "localhost" in resolve_database_url()


class TestTheRefusalsReachThePathThisProjectDocuments:
    """
    ``resolve_database_url`` is the door a bare ``alembic`` comes through,
    and it was the only one the refusals stood at.

    ``flask alembic`` -- the command both guides tell the reader to use,
    and the one the other guide row calls the fix for "No 'script_location'
    key found" -- resolves the URL from the running application and hands
    it to the subprocess in ``ALEMBIC_DATABASE_URL``. That handover is read
    by the first line of ``resolve_database_url``, which returns it
    unexamined, so neither refusal was ever asked on the documented path.

    Measured on a clean checkout with no ``.env`` and no ``FLASK_ENV``::

        flask alembic upgrade head
        Database: sqlite:////.../datas/databases/db_shortener
        INFO  [alembic.runtime.migration] Running upgrade  -> 0001

    -- while the troubleshooting tables of both guides say the reader will
    meet "nothing names a profile" in exactly that situation.

    Two things are held. That the refusal is reachable without going
    through the resolver, and that the CLI asks it. The second is the one
    that was missing, and no test of the first could have found it.
    """

    def test_the_refusal_can_be_asked_of_a_target_somebody_else_resolved(
        self, monkeypatch
    ):
        from link_shortener.infrastructure.configs.app.migration_url import (
            refuse_a_target_a_migration_should_not_touch,
        )

        monkeypatch.setattr(ConfigFactory, "named_env", classmethod(
            lambda cls, env=None: None
        ))
        config = ConfigFactory.create_config_unvalidated("development")

        with pytest.raises(ValueError, match="nothing names a profile"):
            refuse_a_target_a_migration_should_not_touch(
                config, config.get_database_url()
            )

    def test_a_named_profile_is_not_refused(self, monkeypatch):
        """
        The quick start names the profile in ``.env`` and must still work.

        Without this, "make the refusal reachable" could be satisfied by a
        refusal that fires for everybody.
        """
        from link_shortener.infrastructure.configs.app.migration_url import (
            refuse_a_target_a_migration_should_not_touch,
        )

        monkeypatch.setattr(ConfigFactory, "named_env", classmethod(
            lambda cls, env=None: "development"
        ))
        config = ConfigFactory.create_config_unvalidated("development")

        refuse_a_target_a_migration_should_not_touch(
            config, config.get_database_url()
        )

    def test_the_cli_asks_it_before_handing_the_url_over(self, monkeypatch):
        """
        The property that was missing, held at the seam.

        What went wrong was not the refusal but who asked it, so this
        checks the asking. A test of the refusal alone passed throughout.
        """
        from link_shortener.infrastructure.cli.adapters import flask as adapter

        asked = []
        monkeypatch.setattr(
            adapter,
            "refuse_a_target_a_migration_should_not_touch",
            lambda config, url, env=None: asked.append(url),
        )

        class _Config:
            def get_database_url(self):
                return "sqlite:///handed-over.db"

        class _Container:
            config = _Config()

        monkeypatch.setattr(adapter, "_container", lambda: _Container())

        assert adapter._configured_database_url() == "sqlite:///handed-over.db"
        assert asked == ["sqlite:///handed-over.db"]

    def test_a_profile_detached_from_the_environment_is_not_refused(
        self, monkeypatch
    ):
        """
        The refusal reads the environment; ``testing`` does not live there.

        ``IGNORE_ENV`` means the profile was named in code by whoever built
        the configuration, so "did anybody name a profile" is not a
        question about it. Asked anyway, the refusal answered about a
        profile the process is not running: *the 'development' profile
        would migrate sqlite:///:memory:* -- ``development`` resolved from
        an empty environment, ``:memory:`` taken from the ``testing``
        configuration in hand.

        Measured on a checkout with no ``.env``, which is what the clean
        half of CI checks out -- the file is git-ignored and only the
        hostile half writes one: the refusal failed **15** tests of this
        CLI, every one of them ``alembic`` or ``db migrate``. The same
        tests pass in a tree that happens to have a ``.env``, where a named
        ``development`` returns from the refusal early, so the failure was
        invisible to anybody running the suite on a working copy.

        The guard is unweakened, and the test above it says so: a profile
        resolved *from* the environment is still refused.
        """
        from link_shortener.infrastructure.cli.adapters import flask as adapter
        from link_shortener.infrastructure.configs.app.testing import (
            TestingConfig,
        )

        monkeypatch.setattr(ConfigFactory, "named_env", classmethod(
            lambda cls, env=None: None
        ))

        class _Container:
            config = TestingConfig()

        monkeypatch.setattr(adapter, "_container", lambda: _Container())

        assert adapter._configured_database_url() == (
            _Container.config.get_database_url()
        )
