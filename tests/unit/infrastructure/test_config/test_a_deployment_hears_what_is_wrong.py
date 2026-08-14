"""What a deployed profile accepts, refuses, and says while refusing.

Profiles are built from the **environment** rather than from pinned class
attributes: pinning a setting shadows the property that implements it by
MRO, and the code under test then never runs.
"""

import pytest
from sqlalchemy.engine import make_url

from link_shortener.infrastructure.configs.app.production import (
    ProductionConfig
)
from link_shortener.infrastructure.configs.app.staging import StagingConfig


pytestmark = pytest.mark.usefixtures("detached_env")


DEPLOYED_PROFILES = {
    "staging": StagingConfig,
    "production": ProductionConfig,
}

FULLY_CONFIGURED = {
    "SECRET_KEY": "not-the-generated-default",
    "SHORT_CODE_PEPPER": "not-the-generated-default",
    "DOMAIN": "links.example.com",
    "REDIS_ENABLED": "false",
    "DATABASE_TYPE": "postgresql",
    "DATABASE_USER": "shortener",
    "DATABASE_PASSWORD": "s3cret",
    "DATABASE_HOST": "db.internal",
    "DATABASE_NAME": "shortener",
}
"""A deployment that settled everything either profile demands."""


def configure(monkeypatch, **overrides):
    """Write an environment on top of ``FULLY_CONFIGURED``.

    Args:
        monkeypatch: Fixture used to write the environment.
        **overrides: Values to add or replace; ``None`` unsets a variable.
    """
    for name, value in {**FULLY_CONFIGURED, **overrides}.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


def validation_errors(monkeypatch, profile_cls, **overrides):
    """Collect what a profile complains about.

    Args:
        monkeypatch: Fixture used to write the environment.
        profile_cls: Profile to build and validate.
        **overrides: Environment values on top of ``FULLY_CONFIGURED``.

    Returns:
        The error text, or an empty string when the profile validates.
    """
    configure(monkeypatch, **overrides)
    try:
        profile_cls().validate()
    except ValueError as e:
        return str(e)
    return ""


class TestTheDomainIsAHostAndNotSomethingElse:
    """It goes in front of every short link with only a scheme added."""

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_a_domain_carrying_a_scheme_is_refused(
        self, monkeypatch, name, profile_cls
    ):
        """The one an operator copies out of the address bar.

        ``BASE_URL`` would read ``https://https://staging.example.com``.
        """
        errors = validation_errors(
            monkeypatch, profile_cls, DOMAIN="https://staging.example.com"
        )

        # The exact complaint, not the word DOMAIN, which appears in every
        # message this function can produce and in the profile's "must be
        # set" as well.
        assert "not a URL" in errors, (
            f"profile {name} accepted a URL as its domain: {errors!r}"
        )

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_a_domain_carrying_a_path_is_refused(
        self, monkeypatch, name, profile_cls
    ):
        """Short codes are served from the root.

        ``example.com/app`` builds ``https://example.com/app<code>``,
        which resolves to nothing on a service that mounts its codes at
        ``/``.
        """
        errors = validation_errors(
            monkeypatch, profile_cls, DOMAIN="example.com/app"
        )

        assert "not a path" in errors, (
            f"profile {name} accepted a path as its domain: {errors!r}"
        )

    @pytest.mark.parametrize(
        "domain",
        [
            "links.example.com",
            "example.com",
            "links.example.com:8443",
            "xn--80akhbyknj4f.xn--p1ai",
            "кто.рф",
            "[2001:db8::1]",
            "[2001:db8::1]:8443",
        ],
    )
    def test_a_host_is_accepted(self, monkeypatch, domain):
        """The other half: this check must not refuse an ordinary address.

        Without these, every assertion above is satisfied by a check that
        refuses everything. The internationalised pair is here on purpose:
        the rule is about URL syntax that cannot be a host, not about
        which alphabet a host is written in.
        """
        assert validation_errors(monkeypatch, StagingConfig, DOMAIN=domain) == "", (
            f"refused {domain!r}, which is a host"
        )

    def test_the_domain_is_only_checked_when_it_is_set(self, monkeypatch):
        """Absent, it is a fallback in the local profiles rather than a fault.

        The deployed profiles demand it separately -- that demand is
        pinned in ``test_deployed_profiles_demand_what_they_need`` -- and
        this check must not turn an unset ``DOMAIN`` into a syntax
        complaint anywhere else.
        """
        configure(monkeypatch, DOMAIN=None)

        assert StagingConfig()._domain_errors() == []


class TestPostgresqlWithoutAPasswordSetting:
    """Because a password is one of several ways PostgreSQL authenticates."""

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_the_parts_are_accepted_without_a_password(
        self, monkeypatch, name, profile_cls
    ):
        """``peer``, ``trust``, ``.pgpass`` and ``PGPASSWORD`` all do without.

        None of them can put anything in ``DATABASE_PASSWORD``, and the
        refusal was inconsistent as well as wrong: the same connection
        written into ``DATABASE_URL`` passed, because that path reads no
        part.
        """
        errors = validation_errors(
            monkeypatch, profile_cls, DATABASE_PASSWORD=None
        )

        assert errors == "", (
            f"profile {name} refused a passwordless PostgreSQL: {errors!r}"
        )

    def test_the_url_built_without_a_password_names_the_same_database(
        self, monkeypatch
    ):
        """Dropping the demand must not drop the rest of the connection."""
        configure(monkeypatch, DATABASE_PASSWORD=None)
        url = make_url(StagingConfig().get_database_url())

        assert (url.host, url.database, url.username) == (
            "db.internal",
            "shortener",
            "shortener",
        )
        assert url.password in (None, "")

    def test_the_user_is_still_demanded(self, monkeypatch):
        """Only the password stopped being demanded.

        ``DATABASE_USER`` is the one of the three remaining parts that can
        actually be absent: ``DATABASE_HOST`` defaults to ``localhost``
        and ``DATABASE_NAME`` to ``db_shortener``, and a blank value falls
        back to the default rather than through it -- measured, both come
        back as their defaults when set to the empty string. So the check
        on those two is unreachable by configuration, and asserting it
        here would be asserting nothing.

        The message names the part that is missing rather than reciting
        the whole list, so an operator reads which one to write.
        """
        errors = validation_errors(monkeypatch, StagingConfig, DATABASE_USER=None)

        assert "DATABASE_USER" in errors, (
            f"DATABASE_USER was not demanded: {errors!r}"
        )
        assert "DATABASE_PASSWORD" not in errors, (
            f"a missing user was reported as a missing password: {errors!r}"
        )


class TestThePostgresSpellingOfAPostgresqlUrl:
    """``postgres://`` is what half the hosting industry hands out."""

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_a_postgres_url_is_accepted(self, monkeypatch, name, profile_cls):
        """It was refused with advice that could not be followed.

        ``get_backend_name()`` answers ``'postgres'``, so the deployed
        backend check reported "this profile runs on PostgreSQL, and the
        configuration names postgres://..." and told the operator to put a
        PostgreSQL URL there.
        """
        errors = validation_errors(
            monkeypatch,
            profile_cls,
            DATABASE_URL="postgres://u:p@db.internal/shortener",
        )

        assert errors == "", (
            f"profile {name} refused a postgres:// URL: {errors!r}"
        )

    def test_the_url_is_handed_on_in_a_spelling_sqlalchemy_opens(
        self, monkeypatch
    ):
        """Accepting it and leaving it alone would only move the failure.

        SQLAlchemy dropped the alias in 1.4: loading the dialect raises
        ``NoSuchModuleError: Can't load plugin:
        sqlalchemy.dialects:postgres`` -- measured on 2.0.45 -- so a
        configuration that validated would still die at the first
        connection.

        The dialect is resolved rather than an engine built, because
        ``create_engine`` goes on to import the driver: on the default
        ``postgresql://`` that is psycopg2, which this project does not
        install, so the assertion would fail for a reason that has
        nothing to do with the spelling.
        """
        configure(monkeypatch, DATABASE_URL="postgres://u:p@db.internal/shortener")
        url = StagingConfig().get_database_url()

        assert make_url(url).get_backend_name() == "postgresql"
        make_url(url).get_dialect()

    def test_a_driver_written_into_the_scheme_survives(self, monkeypatch):
        """Only the alias is rewritten, not the driver behind it."""
        configure(
            monkeypatch,
            DATABASE_URL="postgres+psycopg2://u:p@db.internal/shortener",
        )

        assert make_url(StagingConfig().get_database_url()).drivername == (
            "postgresql+psycopg2"
        )

    @pytest.mark.parametrize(
        "url",
        [
            "POSTGRES://u:p@db.internal/shortener",
            "Postgres://u:p@db.internal/shortener",
            "POSTGRESQL://u:p@db.internal/shortener",
        ],
        ids=["upper", "mixed", "upper-full-name"],
    )
    def test_the_scheme_is_read_without_regard_to_case(
        self, monkeypatch, url
    ):
        """A URL scheme is case-insensitive by RFC 3986.

        With a case-sensitive comparison ``POSTGRES://`` survives
        unchanged and is then refused with "put a PostgreSQL URL there" --
        the dead end this rewrite exists to
        remove, reached by a different spelling of the same value.
        """
        configure(monkeypatch, DATABASE_URL=url)

        assert make_url(StagingConfig().get_database_url()).drivername == (
            "postgresql+psycopg"
        )
        assert validation_errors(monkeypatch, StagingConfig, DATABASE_URL=url) == ""

    def test_the_rest_of_the_url_is_untouched(self, monkeypatch):
        """A rewrite that loses the password or the port fixes nothing."""
        configure(
            monkeypatch,
            DATABASE_URL="postgres://u:p%40ss@db.internal:6543/shortener",
        )
        url = make_url(StagingConfig().get_database_url())

        assert (url.username, url.password, url.host, url.port, url.database) == (
            "u",
            "p@ss",
            "db.internal",
            6543,
            "shortener",
        )

    def test_a_postgresql_url_with_no_driver_gets_the_installed_one(
        self, monkeypatch
    ):
        """SQLAlchemy's default driver is one this project does not have.

        A bare ``postgresql://`` resolves to psycopg2, and
        ``pyproject.toml`` asks for ``psycopg[binary]`` -- psycopg 3, a
        different module. Renaming the scheme alone turns
        ``NoSuchModuleError`` into ``ModuleNotFoundError: No module named
        'psycopg2'``, which is the same deployment dead at the same
        moment. The URL built from the ``DATABASE_*`` parts has always
        said ``postgresql+psycopg``.
        """
        configure(monkeypatch, DATABASE_URL="postgresql://u:p@db.internal/s")
        url = StagingConfig().get_database_url()

        assert make_url(url).drivername == "postgresql+psycopg"
        make_url(url).get_dialect()

    @pytest.mark.parametrize(
        "url",
        [
            "sqlite:////srv/app.db",
            "mysql+pymysql://u:p@h/db",
            "postgresql+psycopg2://u:p@h/db",
        ],
    )
    def test_a_url_that_names_something_else_is_left_alone(
        self, monkeypatch, url
    ):
        """The rewrite touches the PostgreSQL scheme and nothing else.

        Pinned because a looser rule -- anything starting with
        "postgres" -- would rewrite ``postgresql://`` into
        ``postgresqlql://``, and because a driver the operator named must
        survive even when it is not the one installed.
        """
        configure(monkeypatch, DATABASE_URL=url)

        assert StagingConfig().get_database_url() == url


class TestEveryFaultIsReportedInOneRun:
    """An operator configuring a host should not learn one fault per restart."""

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_four_separate_faults_are_all_named(
        self, monkeypatch, name, profile_cls
    ):
        """All four faults are reported, not the first one alone.

        ``SECRET_KEY`` is a property that raises, and it raised from
        inside ``BaseConfig.validate`` before a single error had been
        collected -- so the three faults after it were never looked for.
        """
        errors = validation_errors(
            monkeypatch,
            profile_cls,
            SECRET_KEY=None,
            DOMAIN=None,
            LOG_LEVEL="LOUD",
            MAX_URL_LENGTH="99999",
        )

        for expected in ("SECRET_KEY", "DOMAIN", "LOG_LEVEL", "MAX_URL_LENGTH"):
            assert expected in errors, (
                f"profile {name} did not report {expected}: {errors!r}"
            )

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_a_missing_secret_does_not_hide_a_missing_database(
        self, monkeypatch, name, profile_cls
    ):
        """The two faults on either side of the old raise.

        ``SECRET_KEY`` was read by the base check and the database URL was
        assembled by the profile's own, afterwards -- so the second was
        unreachable while the first was unset.
        """
        errors = validation_errors(
            monkeypatch, profile_cls, SECRET_KEY=None, DATABASE_USER=None
        )

        assert "SECRET_KEY" in errors, f"profile {name}: {errors!r}"
        assert "DATABASE_USER" in errors, f"profile {name}: {errors!r}"

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_a_fault_is_reported_once(self, monkeypatch, name, profile_cls):
        """Redis is checked by the base class and by the profile.

        The profile's check is the wider one -- it does not stop at
        ``CACHE_ENABLED`` -- and it replaces the base check rather than
        running beside it, so a single missing URL is one complaint.
        """
        errors = validation_errors(
            monkeypatch,
            profile_cls,
            REDIS_ENABLED="true",
            REDIS_URL=None,
            # The cache is off deliberately: with it on, the base rule
            # fires too and this assertion passes whether or not the
            # profile widened anything: with the profiles' wider rule
            # deleted entirely, the CACHE_ENABLED="true" version of this
            # test still passes.
            CACHE_ENABLED="false",
        )

        assert errors.count("REDIS_URL") == 1, (
            f"profile {name} reported one missing URL twice: {errors!r}"
        )


class TestASettingThatWillNotCast:
    """A value the descriptor cannot convert stops the start-up."""

    @pytest.mark.parametrize(
        "variable, value",
        [
            ("PORT", "8O80"),
            ("MAX_URL_LENGTH", "lots"),
            ("BATCH_CREATE_LIMIT", "1.5"),
        ],
    )
    def test_the_unreadable_setting_is_named(self, monkeypatch, variable, value):
        errors = validation_errors(
            monkeypatch, StagingConfig, **{variable: value}
        )

        assert variable in errors, f"{variable}={value!r}: {errors!r}"


class TestAUrlNothingCanParse:
    """``ArgumentError`` is not a ``ValueError``, and it travelled far.

    ``migrations/env.py`` turns a bad setting into a sentence by catching
    ``ValueError``. A URL that will not parse raises ``ArgumentError``
    instead, so it went straight past: measured with
    ``postgres//u:p@host/db`` -- one missing colon --  ``validate()``
    passed clean and ``alembic upgrade`` ended in a traceback.
    """

    @pytest.mark.parametrize(
        "url",
        ["postgres//u:p@db.internal/shortener", "db.internal:5432/shortener"],
    )
    def test_it_is_refused_at_the_check(self, monkeypatch, url):
        errors = validation_errors(monkeypatch, StagingConfig, DATABASE_URL=url)

        assert "DATABASE_URL" in errors, f"accepted {url!r}: {errors!r}"

    def test_the_refusal_is_a_value_error(self, monkeypatch):
        """So the handlers written around ``validate`` still catch it."""
        configure(
            monkeypatch, DATABASE_URL="postgres//u:p@db.internal/shortener"
        )

        with pytest.raises(ValueError):
            StagingConfig().validate()

    def test_a_migration_is_stopped_by_the_same_rule(self, monkeypatch):
        """``validate_database`` is what the bare alembic path runs."""
        configure(
            monkeypatch, DATABASE_URL="postgres//u:p@db.internal/shortener"
        )

        with pytest.raises(ValueError, match="DATABASE_URL"):
            StagingConfig().validate_database()


class TestOneFaultIsOneMessage:
    """An operator reading the same sentence twice looks for a second fault."""

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_an_unsupported_type_is_reported_once(
        self, monkeypatch, name, profile_cls
    ):
        """It reaches the list by two roads.

        ``_database_errors`` names it, and so does the deployed profile
        forcing the URL to be assembled -- ``get_database_url`` raises the
        same sentence.
        """
        errors = validation_errors(
            monkeypatch, profile_cls, DATABASE_URL=None, DATABASE_TYPE="mysql"
        )

        assert errors.count("Unsupported DATABASE_TYPE") == 1, errors


class TestThePartsThatHaveDefaultsAreStillNamed:
    """Dropping the password demand left two settings answering for themselves.

    ``DATABASE_HOST`` defaults to ``localhost`` and ``DATABASE_NAME`` to
    ``db_shortener``, so a deployment that sets only ``DATABASE_TYPE`` and
    a user validates clean and connects to
    ``postgresql+psycopg://shortener@localhost:5432/db_shortener`` -- a
    server and a database nobody named.
    """

    @pytest.mark.parametrize("missing", ["DATABASE_HOST", "DATABASE_NAME"])
    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_an_unnamed_part_is_refused(
        self, monkeypatch, name, profile_cls, missing
    ):
        """Both profiles: the block is a copy, and a copy needs a test.

        Deleted from ``production`` alone, the demand still passes every
        assertion here if they all run against ``staging``.
        """
        errors = validation_errors(
            monkeypatch, profile_cls, DATABASE_URL=None, **{missing: None}
        )

        assert missing in errors, (
            f"profile {name} defaulted {missing} silently: {errors!r}"
        )

    def test_a_named_part_is_accepted(self, monkeypatch):
        """Including one that names exactly what the default would have.

        ``localhost`` is a legitimate answer -- a database on the same
        host -- and the difference is that somebody said it.
        """
        errors = validation_errors(
            monkeypatch,
            StagingConfig,
            DATABASE_URL=None,
            DATABASE_HOST="localhost",
            DATABASE_NAME="db_shortener",
        )

        assert errors == "", errors

    def test_the_demand_does_not_apply_when_a_url_names_the_database(
        self, monkeypatch
    ):
        """The parts are not read at all once ``DATABASE_URL`` is set."""
        errors = validation_errors(
            monkeypatch,
            StagingConfig,
            DATABASE_HOST=None,
            DATABASE_NAME=None,
            DATABASE_URL="postgresql+psycopg://u:p@db.internal/shortener",
        )

        assert errors == "", errors


class TestTheEngineIsToldWhatItIsTalkingTo:
    """``DATABASE_TYPE`` says how to assemble a URL, not what was assembled.

    It defaults to ``sqlite`` and is not read at all once ``DATABASE_URL``
    is set, yet it was what the engine was configured from: measured, a
    deployment naming PostgreSQL in ``DATABASE_URL`` alone got SQLite's
    engine settings -- no pool sizing, no connect or statement timeout,
    and ``PRAGMA foreign_keys=ON`` issued on every PostgreSQL connection.
    """

    def test_the_backend_follows_the_url(self, monkeypatch):
        configure(
            monkeypatch,
            DATABASE_URL="postgresql+psycopg://u:p@db.internal/shortener",
            DATABASE_TYPE=None,
        )

        profile = StagingConfig()
        assert profile.DATABASE_TYPE == "sqlite", "the setting is unchanged"
        assert profile.database_backend() == "postgresql"

    def test_a_sqlite_url_still_reads_as_sqlite(self, monkeypatch):
        """The local path must keep its PRAGMA and skip the pool settings."""
        configure(monkeypatch, DATABASE_URL="sqlite:////srv/app.db")

        assert StagingConfig().database_backend() == "sqlite"

    def test_an_unbuildable_url_falls_back_to_the_setting(self, monkeypatch):
        """No worse than what it replaced, when there is nothing to read."""
        configure(
            monkeypatch,
            DATABASE_URL=None,
            DATABASE_TYPE="postgresql",
            DATABASE_USER=None,
        )

        assert StagingConfig().database_backend() == "postgresql"


class TestTheLoggedUrlSaysWhetherAPasswordWasSent:
    """``:***`` for an empty password reads as "a password is set".

    Now that a PostgreSQL connection may legitimately carry none -- peer,
    trust, ``.pgpass``, ``PGPASSWORD`` -- the difference matters to the
    operator reading a startup line while debugging authentication.
    """

    def test_no_password_is_shown_as_no_password(self, monkeypatch):
        configure(
            monkeypatch, DATABASE_URL=None, DATABASE_PASSWORD=None
        )

        shown = StagingConfig().display_database_url
        assert "***" not in shown, shown
        assert "shortener@db.internal" in shown, shown

    def test_a_password_is_still_masked(self, monkeypatch):
        configure(monkeypatch, DATABASE_URL=None)

        shown = StagingConfig().display_database_url
        assert "***" in shown, shown
        assert "s3cret" not in shown, shown


class TestThePoolFollowsTheBackendThatWillBeOpened:
    """``DATABASE_TYPE`` decided this too, and it defaults to sqlite.

    On a deployment naming PostgreSQL in ``DATABASE_URL`` alone all three
    pool settings come back 0, so the engine takes SQLAlchemy's defaults --
    ``pool_size`` 5 where the configuration said otherwise, and
    ``pool_recycle`` never switched on -- and ``DATABASE_POOL_SIZE`` in
    the environment was not even read.
    """

    def test_a_postgresql_url_gets_the_configured_pool(self, monkeypatch):
        configure(
            monkeypatch,
            DATABASE_TYPE=None,
            DATABASE_URL="postgresql+psycopg://u:p@db.internal/short",
            DATABASE_POOL_SIZE="41",
            DATABASE_POOL_RECYCLE="47",
        )

        pool = StagingConfig().get_pool_params()

        assert pool["pool_size"] == 41
        assert pool["pool_recycle"] == 47

    def test_a_sqlite_url_still_gets_no_pool(self, monkeypatch):
        """SQLite takes none of these, and passing them raises."""
        configure(
            monkeypatch,
            DATABASE_TYPE="postgresql",
            DATABASE_URL="sqlite:////srv/app.db",
            DATABASE_POOL_SIZE="41",
        )

        assert StagingConfig().get_pool_params()["pool_size"] == 0


class TestThePoolSettingsReachTheEngine:
    """Checking a value is half the job; it has to arrive as written.

    ``DatabaseManager`` dropped every falsy pool parameter along with the
    ``None``s, which silently reversed two of them: measured,
    ``DATABASE_MAX_OVERFLOW=0`` -- an operator capping the pool at
    ``pool_size`` -- arrived as SQLAlchemy's default of 10, and
    ``DATABASE_POOL_RECYCLE=0`` arrived as -1, which is "never recycle"
    rather than "recycle at once".
    """

    @staticmethod
    def _engine_pool(**pool_params):
        """Build an engine the way the container does and read its pool.

        Args:
            **pool_params: What the configuration would hand over.

        Returns:
            The engine's pool object.
        """
        from link_shortener.infrastructure.database.manager import (
            DatabaseManager
        )

        # The pool settings are **kwargs on the manager, which is how the
        # container passes them: ``**config.get_pool_params()``.
        manager = DatabaseManager(
            database_url="postgresql+psycopg://u:p@db.internal/short",
            echo=False,
            database_type="postgresql",
            **{
                "pool_size": 5,
                "max_overflow": 10,
                "pool_recycle": 3600,
                "pool_pre_ping": True,
                **pool_params,
            },
        )
        manager.connect()
        return manager.engine.pool

    def test_a_zero_overflow_is_not_turned_into_ten(self):
        pool = self._engine_pool(max_overflow=0)

        assert pool._max_overflow == 0

    def test_a_zero_recycle_is_not_turned_into_never(self):
        """The reversal that mattered: 0 and -1 are opposite instructions."""
        pool = self._engine_pool(pool_recycle=0)

        assert pool._recycle == 0

    def test_minus_one_still_arrives_as_itself(self):
        pool = self._engine_pool(max_overflow=-1, pool_recycle=-1)

        assert pool._max_overflow == -1
        assert pool._recycle == -1

    def test_a_none_is_still_dropped(self):
        """The half of the filter that survived, and nothing reached it.

        ``get_pool_params`` never produces ``None``, so this is about the
        manager's own contract: it takes pool parameters as ``**kwargs``
        from anywhere, and ``create_engine`` refuses a ``None`` where it
        wants an integer. With the filter removed entirely, everything
        else in the suite still passes.
        """
        pool = self._engine_pool(pool_recycle=None)

        assert pool._recycle == -1, "None reached create_engine"

    def test_an_ordinary_pool_is_unchanged(self):
        """The control: dropping the filter must not drop the settings."""
        pool = self._engine_pool()

        assert pool.size() == 5
        assert pool._max_overflow == 10
        assert pool._recycle == 3600


class TestTheRefusalIsVisibleBeforeTheTraceback:
    """The list is useless at the bottom of twenty-five frames.

    ``create_config`` raises, the exception travels out through
    ``create_app`` and Flask's own ``find_best_app``, and what an
    operator sees is a stack trace with the useful part last: on a
    ``production`` profile missing ``DOMAIN``, 25 frames and then the two
    sentences that say what to fix.
    """

    def test_the_errors_are_printed_to_stderr(self, monkeypatch, capsys):
        from link_shortener.infrastructure.configs.app.factory import (
            ConfigFactory
        )

        configure(monkeypatch, DOMAIN=None)
        monkeypatch.setenv("FLASK_ENV", "staging")

        with pytest.raises(ValueError):
            ConfigFactory.create_config("staging")

        printed = capsys.readouterr().err
        assert "Configuration errors" in printed
        assert "DOMAIN" in printed

    def test_the_profile_is_named_beside_them(self, monkeypatch, capsys):
        """Which profile refused is half the answer.

        The same settings are fine under ``development``, so an operator
        reading a refusal needs to know which configuration produced it
        and where its values come from.
        """
        from link_shortener.infrastructure.configs.app.factory import (
            ConfigFactory
        )

        configure(monkeypatch, DOMAIN=None)
        monkeypatch.setenv("FLASK_ENV", "production")

        with pytest.raises(ValueError):
            ConfigFactory.create_config("production")

        printed = capsys.readouterr().err
        assert "Profile: production" in printed
        assert ".env" in printed

    def test_a_configuration_that_validates_prints_nothing(
        self, monkeypatch, capsys
    ):
        """The other half: this must not narrate a successful start."""
        from link_shortener.infrastructure.configs.app.factory import (
            ConfigFactory
        )

        configure(monkeypatch)
        monkeypatch.setenv("FLASK_ENV", "staging")
        ConfigFactory.create_config("staging")

        assert capsys.readouterr().err == ""
