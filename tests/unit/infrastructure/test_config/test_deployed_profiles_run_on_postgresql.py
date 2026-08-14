"""
Which backend each profile may run on.

``DATABASE_TYPE`` defaults to ``sqlite`` and ``DATABASE_NAME`` to
``db_shortener``, so without this rule a deployment that configured
neither starts without a word on a new empty file in the project root --
under ``production`` with everything else it demands settled: ``SECRET_KEY``,
``SHORT_CODE_PEPPER``, ``DOMAIN``, and ``REDIS_ENABLED`` off -- the
configuration validated clean and opened
``sqlite:////<root>/db_shortener``. The service then answers as if the
data had never existed, and nothing in the startup line reads as a
failure.

The rule is the backend rather than the omission, because SQLite is
reached by several roads and each ends the same way: an unnamed file is
created empty, a relative path in ``DATABASE_URL`` follows the working
directory of whichever process opened it, and an in-memory URL hands
every thread its own database. ``development`` keeps both backends --
that is what the default is for.

What this does not close is pinned in ``TestTheHalfThisDoesNotClose``:
a profile nobody named stays ``development`` and starts on the default
file, where a migration in the same situation refuses.
"""

import pytest

from link_shortener.infrastructure.configs.app import base
from link_shortener.infrastructure.configs.app.base import BaseConfig
from link_shortener.infrastructure.configs.app.development import (
    DevelopmentConfig
)
from link_shortener.infrastructure.configs.app.factory import ConfigFactory
from link_shortener.infrastructure.configs.app.migration_url import (
    HANDOFF_ENV_VAR, resolve_database_url
)
from link_shortener.infrastructure.configs.app.production import (
    ProductionConfig
)
from link_shortener.infrastructure.configs.app.staging import StagingConfig
from link_shortener.infrastructure.configs.app.testing import TestingConfig


DEPLOYED_PROFILES = {
    "staging": StagingConfig,
    "production": ProductionConfig,
}

SATISFIED_ELSEWHERE = {
    "SECRET_KEY": "not-the-generated-default",
    "SHORT_CODE_SECRET_PEPPER": "not-the-generated-default",
    "DOMAIN": "links.example.com",
    "REDIS_ENABLED": False,
}
"""What a deployed profile wants apart from the database.

Three are demanded outright; ``REDIS_ENABLED`` is switched off instead,
because leaving it on demands a ``REDIS_URL`` in turn. Pinned so that
each assertion below measures the backend rule alone: left out,
``ProductionConfig.validate()`` raises about ``SECRET_KEY`` from a
property before any list of errors exists, and a test asserting "this
configuration is refused" would pass for the wrong reason.
"""

POSTGRESQL_PARTS = {
    "DATABASE_TYPE": "postgresql",
    "DATABASE_USER": "shortener",
    "DATABASE_PASSWORD": "s3cret",
    "DATABASE_HOST": "db.internal",
    "DATABASE_NAME": "shortener",
}

# Variables that decide which database is opened, cleared so that a
# developer's own exported settings cannot answer for a test.
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
    "SECRET_KEY",
    "SHORT_CODE_PEPPER",
    "DOMAIN",
    "REDIS_ENABLED",
    "REDIS_URL",
)


def config(profile_cls=BaseConfig, **attrs):
    """Build a profile detached from the environment.

    Args:
        profile_cls: Profile to derive from.
        **attrs: Settings to pin as plain attributes, which shadow the
            environment-backed descriptors.

    Returns:
        An instance answering only from its own defaults.
    """
    detached = type("Detached", (profile_cls,), {"IGNORE_ENV": True, **attrs})
    return detached()


def validation_errors(profile_cls, **attrs):
    """Collect what a profile complains about.

    Args:
        profile_cls: Profile to derive from.
        **attrs: Settings to pin on top of ``SATISFIED_ELSEWHERE``.

    Returns:
        The error text, or an empty string when the profile validates.
    """
    try:
        config(profile_cls, **{**SATISFIED_ELSEWHERE, **attrs}).validate()
    except ValueError as e:
        return str(e)
    return ""


class TestADeployedProfileRefusesEverythingButPostgresql:
    """Every road to SQLite, and what the refusal tells the operator."""

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_the_default_backend_is_refused(self, name, profile_cls):
        """Nothing configured, which is how the file appeared at all."""
        errors = validation_errors(profile_cls)

        assert "this profile runs on PostgreSQL" in errors, (
            f"profile {name} started on the default SQLite file: {errors!r}"
        )

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_a_hand_written_sqlite_name_is_refused(self, name, profile_cls):
        """Nothing fell back to a default here, and it is still SQLite."""
        errors = validation_errors(
            profile_cls,
            DATABASE_TYPE="sqlite",
            DATABASE_NAME="/srv/link-shortener/live.db",
        )

        assert "this profile runs on PostgreSQL" in errors, (
            f"profile {name} accepted a SQLite file: {errors!r}"
        )

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_a_sqlite_file_named_in_the_url_is_refused(
        self, name, profile_cls
    ):
        """``DATABASE_URL`` is not a way around the backend rule.

        It also skips the anchoring ``DATABASE_NAME`` gets, so this is
        the form that follows the working directory of whichever process
        opened it.
        """
        errors = validation_errors(
            profile_cls, DATABASE_URL="sqlite:////srv/shortener/live.db"
        )

        assert "this profile runs on PostgreSQL" in errors, (
            f"profile {name} accepted a SQLite URL: {errors!r}"
        )

    @pytest.mark.parametrize(
        "url",
        ["sqlite://", "sqlite:///", "sqlite:///:memory:",
         "sqlite:///file::memory:?cache=shared&uri=true"],
    )
    def test_a_database_that_lives_inside_the_process_is_refused(self, url):
        """All four vanish with the process, and a migration refuses all
        four already.

        Three of them are worse than that: SQLAlchemy pools them with
        ``SingletonThreadPool``, so a table one worker thread created was
        measured invisible to the next. The shared-cache form is the
        exception -- ``QueuePool``, and the table is visible -- which
        leaves it merely empty at every restart.
        """
        errors = validation_errors(ProductionConfig, DATABASE_URL=url)

        assert "this profile runs on PostgreSQL" in errors, (
            f"production accepted {url!r}: {errors!r}"
        )

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_a_sqlite_url_beats_a_postgresql_type(self, name, profile_cls):
        """The likeliest half-migrated configuration there is.

        ``DATABASE_URL`` is returned before any part is read, so a
        deployment that set the type and the parts but left an old
        SQLite URL in place runs on SQLite. Checking the type instead of
        the assembled URL would accept exactly this.
        """
        errors = validation_errors(
            profile_cls,
            **POSTGRESQL_PARTS,
            DATABASE_URL="sqlite:////srv/shortener/live.db",
        )

        assert "this profile runs on PostgreSQL" in errors, (
            f"profile {name} read the type instead of the URL: {errors!r}"
        )

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_every_part_but_the_type_is_still_refused(
        self, name, profile_cls
    ):
        """One forgotten line, and the server settings are decoration.

        Everything points at a real server except ``DATABASE_TYPE``,
        which still says SQLite -- so the parts are never used and the
        profile opens a file. A check excused by "the operator clearly
        configured a server" would let this through.
        """
        errors = validation_errors(
            profile_cls,
            DATABASE_USER="shortener",
            DATABASE_PASSWORD="s3cret",
            DATABASE_HOST="db.internal",
            DATABASE_NAME="shortener",
        )

        assert "this profile runs on PostgreSQL" in errors, (
            f"profile {name} took the parts for a decision: {errors!r}"
        )

    def test_a_database_file_that_already_holds_data_is_refused(
        self, tmp_path
    ):
        """An existing file is not evidence that anybody chose it.

        It is the likeliest thing to find on a host that has been
        running on SQLite by accident, and the one the documented
        migration path is for.
        """
        existing = tmp_path / "live.db"
        existing.write_bytes(b"SQLite format 3\x00" + b"\x00" * 200)

        errors = validation_errors(
            ProductionConfig, DATABASE_URL=f"sqlite:///{existing}"
        )

        assert "this profile runs on PostgreSQL" in errors, (
            f"production accepted a populated file: {errors!r}"
        )

    def test_the_rule_does_not_depend_on_the_working_directory(
        self, tmp_path, monkeypatch
    ):
        """A deployment starts wherever its unit file says.

        Nothing about the backend follows from where the process was
        started, and a check that read the layout around it -- a
        ``pyproject.toml`` or an ``.env`` beside the process -- would be
        off in production and on in a checkout, which no test run from
        the repository would notice.
        """
        monkeypatch.chdir(tmp_path)

        errors = validation_errors(ProductionConfig)

        assert "this profile runs on PostgreSQL" in errors, (
            f"the rule followed the working directory: {errors!r}"
        )

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_the_refusal_names_the_database_it_would_have_opened(
        self, name, profile_cls
    ):
        """An operator who set nothing has nothing to search for.

        Checked against the URL the profile would really open, asked of
        ``get_database_url`` rather than spelled out here: a refusal naming
        the bare default, without the path that makes it
        findable, has to fail this.
        """
        profile = config(profile_cls, **SATISFIED_ELSEWHERE)
        errors = validation_errors(profile_cls)

        assert profile.get_database_url() in errors, (
            f"profile {name} refused without saying what it would have "
            f"opened: {errors!r}"
        )

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_the_refusal_says_which_settings_carry_the_answer(
        self, name, profile_cls
    ):
        """A refusal an operator cannot act on costs a support round.

        Both routes are named because both work: the parts, or the whole
        URL. Asserted on ``DATABASE_TYPE=postgresql`` rather than on
        ``DATABASE_URL``, which the first sentence contains anyway.
        """
        errors = validation_errors(profile_cls)

        assert "DATABASE_TYPE=postgresql" in errors, (
            f"profile {name} refused without saying what to set: {errors!r}"
        )

    def test_the_remedy_fits_a_database_named_in_the_url(self):
        """Advice that cannot work is worse than none.

        With one message for both cases: told to set ``DATABASE_TYPE``
        and the parts while a SQLite ``DATABASE_URL`` is in place, an
        operator following it exactly gets the same
        refusal, because the URL is returned before a part is read.
        """
        errors = validation_errors(
            ProductionConfig, DATABASE_URL="sqlite:////srv/live.db"
        )

        assert "DATABASE_URL decides on its own" in errors, errors
        assert "Set DATABASE_TYPE=postgresql with" not in errors, errors

    def test_another_backend_is_not_explained_by_sqlite(self):
        """The refusal covers every backend; the reasoning does not.

        MySQL is refused for being the wrong server, not for starting
        empty, and telling the operator about SQLite would describe a
        database they never configured.
        """
        errors = validation_errors(
            ProductionConfig, DATABASE_URL="mysql+pymysql://u:p@h/db"
        )

        assert "this profile runs on PostgreSQL" in errors, errors
        assert "SQLite" not in errors, errors


class TestPostgresqlIsAccepted:
    """The backend a deployment is supposed to be on, both ways of naming."""

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_the_parts_are_accepted(self, name, profile_cls):
        errors = validation_errors(profile_cls, **POSTGRESQL_PARTS)

        assert errors == "", f"profile {name} refused postgresql: {errors!r}"

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_a_whole_url_is_accepted(self, name, profile_cls):
        errors = validation_errors(
            profile_cls,
            DATABASE_URL="postgresql+psycopg://u:p@db.internal:5432/short",
        )

        assert errors == "", f"profile {name} refused a URL: {errors!r}"


class TestAConfigurationThatCannotBuildAUrl:
    """A URL that will not assemble is somebody else's complaint."""

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_the_backend_rule_stays_out_of_it(self, name, profile_cls):
        """Incomplete PostgreSQL parts must not read as the wrong backend.

        ``get_database_url`` raises here rather than returning anything,
        and the backend cannot be known. Answering "this profile runs on
        PostgreSQL" would tell an operator to set what they already set.
        """
        errors = validation_errors(
            profile_cls, DATABASE_TYPE="postgresql", DATABASE_USER=""
        )

        assert "runs on PostgreSQL" not in errors, (
            f"profile {name} blamed the backend for a missing part: "
            f"{errors!r}"
        )

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_a_deployed_profile_still_reports_the_missing_parts(
        self, name, profile_cls
    ):
        """And the real complaint has to survive, not be swallowed.

        Both deployed profiles force the URL to be built, so both reach
        the complaint. ``staging`` did not until it gained a ``validate``
        of its own: it passed this configuration and failed at the first
        connection instead.
        """
        errors = validation_errors(
            profile_cls, DATABASE_TYPE="postgresql", DATABASE_USER=""
        )

        assert "PostgreSQL connection requires" in errors, (
            f"profile {name} swallowed the missing parts: {errors!r}"
        )


class TestTheLocalProfilesKeepBothBackends:
    """Where SQLite is the point rather than the problem."""

    def test_development_may_use_sqlite(self):
        """The whole local workflow is this file and no configuration."""
        assert validation_errors(DevelopmentConfig) == ""

    def test_development_may_use_postgresql_too(self):
        """Developing against the deployed backend has to stay possible."""
        assert validation_errors(DevelopmentConfig, **POSTGRESQL_PARTS) == ""

    def test_testing_is_not_held_to_the_rule(self):
        """``TestingConfig`` is detached and pins its own in-memory URL.

        Either would excuse it on its own, so this asserts no more than
        that the profile validates: a test run is not a deployment.
        """
        assert validation_errors(TestingConfig) == ""

    def test_the_base_profile_is_not_held_to_the_rule(self):
        """``BaseConfig`` is what a test subclasses, not what a host runs.

        It carries ``DEBUG = True``, which is how the rule tells a local
        profile from a deployed one; ``production`` and ``staging`` both
        say ``DEBUG = False``.
        """
        assert validation_errors(BaseConfig) == ""


class TestTheRuleHoldsThroughTheEnvironment:
    """Not only against profiles a test assembled by hand.

    Everything above pins settings as class attributes on a detached
    profile. That leaves one way to narrow the check invisibly: excuse
    whatever the operator wrote in the environment, which no detached
    profile reads. Two such rewrites pass everything else in the suite.
    """

    @pytest.fixture(autouse=True)
    def only_what_the_test_sets(self, monkeypatch):
        """Detach resolution from this machine and from the repository."""
        monkeypatch.setattr(
            ConfigFactory, "_read_env_file", staticmethod(lambda filename: {})
        )
        for name in DATABASE_VARS:
            monkeypatch.delenv(name, raising=False)

    @pytest.fixture
    def deployed_environment(self, monkeypatch):
        """Set everything a production start needs except the database."""
        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv("SECRET_KEY", "not-the-generated-default")
        monkeypatch.setenv("SHORT_CODE_PEPPER", "not-the-generated-default")
        monkeypatch.setenv("DOMAIN", "links.example.com")
        monkeypatch.setenv("REDIS_ENABLED", "false")

    def test_an_exported_database_type_does_not_excuse_sqlite(
        self, deployed_environment, monkeypatch
    ):
        """Writing the setting out by hand is not a licence for it."""
        monkeypatch.setenv("DATABASE_TYPE", "sqlite")
        monkeypatch.setenv("DATABASE_NAME", "/srv/shortener/live.db")

        with pytest.raises(ValueError, match="runs on PostgreSQL"):
            ConfigFactory.create_config()

    def test_an_exported_url_does_not_excuse_sqlite(
        self, deployed_environment, monkeypatch
    ):
        monkeypatch.setenv("DATABASE_URL", "sqlite:////srv/shortener/live.db")

        with pytest.raises(ValueError, match="runs on PostgreSQL"):
            ConfigFactory.create_config()

    def test_exported_server_settings_do_not_excuse_the_type(
        self, deployed_environment, monkeypatch
    ):
        """A server in the environment is not a backend decision.

        Every part points at a real PostgreSQL host and only
        ``DATABASE_TYPE`` was forgotten, so the parts are never read and
        the profile opens a file. A check excused by "an operator who
        exported DATABASE_HOST clearly configured a server" passes
        everything else while production starts on SQLite.
        """
        monkeypatch.setenv("DATABASE_HOST", "db.internal")
        monkeypatch.setenv("DATABASE_USER", "shortener")
        monkeypatch.setenv("DATABASE_PASSWORD", "s3cret")
        monkeypatch.setenv("DATABASE_NAME", "shortener")

        with pytest.raises(ValueError, match="runs on PostgreSQL"):
            ConfigFactory.create_config()

    def test_an_installed_copy_is_held_to_the_rule(
        self, deployed_environment, monkeypatch
    ):
        """Outside a source tree is where a deployment actually runs.

        ``PROJECT_ROOT`` is ``None`` in the image: the package lives in
        ``site-packages`` and the two markers it is found by are not
        copied there. A check that consulted it would therefore switch
        itself off in the one place that matters, and a suite running
        from the tree would never see it -- measured, adding that single
        condition left all 1527 tests green.

        Both legs have to be broken at once, which is why this lives
        here and not among the detached profiles: a rewrite can excuse
        itself by the missing tree *or* by reading the environment, and
        a test that covers one leg only lets the other through.

        The finder is stubbed as well as the global it filled. Asking
        ``_find_project_root()`` again instead of reading ``PROJECT_ROOT``
        is the same excuse spelled differently, and it slips past a version
        of this test that pins only the global.
        """
        monkeypatch.setattr(base, "PROJECT_ROOT", None)
        monkeypatch.setattr(base, "_find_project_root", lambda: None)
        monkeypatch.setenv("DATABASE_TYPE", "sqlite")

        with pytest.raises(ValueError, match="runs on PostgreSQL"):
            ConfigFactory.create_config()

    def test_an_exported_postgresql_url_starts(
        self, deployed_environment, monkeypatch
    ):
        """The counterweight: the refusals above must be about SQLite.

        Without this, a check that refused every production start would
        satisfy both of them.
        """
        monkeypatch.setenv(
            "DATABASE_URL", "postgresql+psycopg://u:p@db.internal:5432/short"
        )

        assert ConfigFactory.create_config().get_database_url().startswith(
            "postgresql"
        )


class TestTheHalfThisDoesNotClose:
    """An unnamed profile keeps the default it always had.

    Pinned deliberately. The migration refuses this case and the
    application does not: ``DEFAULT_ENV`` is ``development`` for a host
    and for the stack alike, and a refusal here would stop the developer
    who configured nothing on purpose.
    """

    @pytest.fixture(autouse=True)
    def only_what_the_test_sets(self, monkeypatch):
        """Detach resolution from this machine and from the repository.

        The ``.env`` in the working tree names ``development`` already,
        which would make an unnamed profile impossible to test for.
        """
        monkeypatch.setattr(
            ConfigFactory, "_read_env_file", staticmethod(lambda filename: {})
        )
        for name in DATABASE_VARS:
            monkeypatch.delenv(name, raising=False)

    def test_an_unnamed_profile_starts_on_the_default_file(self):
        assert ConfigFactory.named_env() is None

        url = ConfigFactory.create_config().get_database_url()

        # The file, not merely "some SQLite": an in-memory default would
        # be a different bug wearing the same prefix.
        assert url.startswith("sqlite:") and "db_shortener" in url
        assert ":memory:" not in url

    def test_the_migration_still_refuses_what_the_application_allows(self):
        """The counterweight, and the reason this is not a contradiction.

        A migration writes a schema and leaves; an application on the
        wrong database is caught by the first request. Pinned so that a
        change loosening the migration cannot pass as "the application
        allows this too".
        """
        with pytest.raises(ValueError, match="nothing names a profile"):
            resolve_database_url()

    def test_a_named_production_profile_is_still_refused(self, monkeypatch):
        """The pin above must not read as "the check never fires here"."""
        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv("SECRET_KEY", "not-the-generated-default")
        monkeypatch.setenv("SHORT_CODE_PEPPER", "not-the-generated-default")
        monkeypatch.setenv("DOMAIN", "links.example.com")
        monkeypatch.setenv("REDIS_ENABLED", "false")

        with pytest.raises(ValueError, match="runs on PostgreSQL"):
            ConfigFactory.create_config()


class TestTheMigrationPathIsNotDisturbed:
    """A migration validates less, and must keep validating less."""

    def test_validate_database_stays_silent_about_the_backend(self):
        """``validate_database`` is the migration's half of ``validate``.

        Putting this refusal in the shared list would reach a migration
        too -- and a migration against SQLite is legitimate under
        ``development``, which is exactly the caller that path serves.
        """
        config(ProductionConfig, **SATISFIED_ELSEWHERE).validate_database()
