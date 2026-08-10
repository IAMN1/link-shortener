"""
Tests for the configuration contract: how a profile, `.env.<profile>`, `.env`
and real environment variables combine.

The rules under test (documented in README and docs/QUICKSTART.md):

    real environment variable  >  .env.<profile>  >  .env  >  profile default

plus: the `testing` profile is fully detached from the environment.

Each test runs in an isolated temporary directory so it never picks up the
developer's real `.env`.
"""

import os

import pytest

from link_shortener.infrastructure.configs.app.development import DevelopmentConfig
from link_shortener.infrastructure.configs.app.env import (
    EnvField, env_bool, env_float, env_int, env_list, env_str
)
from link_shortener.infrastructure.configs.app import factory as factory_module
from link_shortener.infrastructure.configs.app.factory import ConfigFactory
from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.infrastructure.configs.app.base import MAX_BATCH_ITEMS


# Prefixes covering every setting that decides what this test run connects
# to. Scrubbed by prefix rather than by name because the named list missed
# DATABASE_TYPE, DATABASE_NAME, DATABASE_HOST, DATABASE_USER and
# DATABASE_PASSWORD -- it removed only DATABASE_URL. These tests build a
# real application through the `development` profile, which unlike `testing`
# is not detached from the environment, and startup seeds roles. A developer
# or CI runner with a PostgreSQL setup exported -- the ordinary state --
# therefore had this file connect to that database and write to it.
# Measured: a run added four rows to the `roles` table of an outside
# database and reported two tests passed.
SCRUBBED_PREFIXES = ("DATABASE_", "REDIS_", "CELERY_", "CACHE_", "AUTO_SEED_")

SCRUBBED_NAMES = (
    "FLASK_ENV", "PORT", "HOST", "LOGGER_TYPE", "CORS_ORIGINS",
    "GUEST_LINK_LIMIT", "SQLALCHEMY_ECHO",
    "BATCH_CREATE_LIMIT", "FLASK_RUN_FROM_CLI",
)


@pytest.fixture()
def env_dir(tmp_path, monkeypatch):
    """Run inside an empty directory with a clean, predictable environment.

    The project root is pointed at that directory too. ``chdir`` alone
    stopped being isolation once ``_read_env_file`` began reading the root
    first: the root is derived from the module's own location, so it is
    the developer's checkout no matter where the test runs, and these
    tests would have read the developer's real ``.env`` -- the one thing
    the docstring above promises they never do.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(factory_module, "PROJECT_ROOT", tmp_path)
    for name in SCRUBBED_NAMES:
        monkeypatch.delenv(name, raising=False)
    for name in list(os.environ):
        if name.startswith(SCRUBBED_PREFIXES):
            monkeypatch.delenv(name, raising=False)
    return tmp_path


def write(path, **values):
    """Write a `.env`-style file."""
    path.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()),
        encoding="utf-8",
    )


# ------------------------------------------------------------------
# TestPrecedence
# ------------------------------------------------------------------
class TestPrecedence:
    """Tests for the four-level precedence chain."""

    def test_profile_default_used_when_nothing_is_set(self, env_dir):
        """Should fall back to the value declared by the profile."""
        config = ConfigFactory.create_config("development")

        assert config.GUEST_LINK_LIMIT == 10

    def test_dotenv_overrides_profile_default(self, env_dir):
        """Should prefer `.env` over the profile default."""
        write(env_dir / ".env", GUEST_LINK_LIMIT=99)

        config = ConfigFactory.create_config("development")

        assert config.GUEST_LINK_LIMIT == 99

    def test_profile_file_overrides_dotenv(self, env_dir):
        """Should prefer `.env.<profile>` over `.env`."""
        write(env_dir / ".env", GUEST_LINK_LIMIT=99, LOGGER_TYPE="from-dotenv")
        write(env_dir / ".env.development", GUEST_LINK_LIMIT=55)

        config = ConfigFactory.create_config("development")

        assert config.GUEST_LINK_LIMIT == 55
        # A key only present in `.env` is still applied.
        assert config.LOGGER_TYPE == "from-dotenv"

    def test_real_environment_wins_over_both_files(self, env_dir, monkeypatch):
        """Should prefer an exported variable over any `.env` file."""
        write(env_dir / ".env", GUEST_LINK_LIMIT=99)
        write(env_dir / ".env.development", GUEST_LINK_LIMIT=55)
        monkeypatch.setenv("GUEST_LINK_LIMIT", "7")

        config = ConfigFactory.create_config("development")

        assert config.GUEST_LINK_LIMIT == 7

    def test_precedence_holds_when_dotenv_was_preloaded(self, env_dir, monkeypatch):
        """
        Should still prefer `.env.<profile>` when `.env` is already in the
        environment.

        The Flask CLI loads `.env` into os.environ before the application is
        imported; the profile file must not lose to those values.
        """
        write(env_dir / ".env", GUEST_LINK_LIMIT=1001)
        write(env_dir / ".env.development", GUEST_LINK_LIMIT=2001)
        # Simulate what `flask` does before create_app() runs.
        monkeypatch.setenv("FLASK_RUN_FROM_CLI", "true")
        monkeypatch.setenv("GUEST_LINK_LIMIT", "1001")

        config = ConfigFactory.create_config("development")

        assert config.GUEST_LINK_LIMIT == 2001

    def test_exported_value_wins_outside_flask_cli(self, env_dir, monkeypatch):
        """
        Should keep an exported variable even when it equals the `.env` entry.

        Without the Flask CLI nothing injects `.env` on our behalf, so anything
        already in os.environ was exported deliberately and must not be
        replaced by `.env.<profile>`.
        """
        write(env_dir / ".env", GUEST_LINK_LIMIT=1001)
        write(env_dir / ".env.development", GUEST_LINK_LIMIT=2001)
        monkeypatch.delenv("FLASK_RUN_FROM_CLI", raising=False)
        monkeypatch.setenv("GUEST_LINK_LIMIT", "1001")

        config = ConfigFactory.create_config("development")

        assert config.GUEST_LINK_LIMIT == 1001

    def test_blank_variable_does_not_mask_dotenv(self, env_dir, monkeypatch):
        """
        Should fall through to `.env` when the variable is blank.

        docker compose substitutes an empty string for every ${VAR} that is
        missing from the env file; that must not hide a value configured in
        `.env` and silently drop the setting back to the code default.
        """
        write(env_dir / ".env", LOG_LEVEL="INFO", GUEST_LINK_LIMIT=25)
        monkeypatch.setenv("LOG_LEVEL", "")
        monkeypatch.setenv("GUEST_LINK_LIMIT", "   ")

        config = ConfigFactory.create_config("development")

        assert config.LOG_LEVEL == "INFO"
        assert config.GUEST_LINK_LIMIT == 25


# ------------------------------------------------------------------
# TestProfileResolution
# ------------------------------------------------------------------
class TestProfileResolution:
    """Tests for choosing the configuration profile."""

    def test_flask_env_from_real_environment(self, env_dir, monkeypatch):
        """Should read the profile from FLASK_ENV."""
        monkeypatch.setenv("FLASK_ENV", "testing")

        assert ConfigFactory.resolve_env() == "testing"

    def test_flask_env_from_dotenv(self, env_dir):
        """Should read the profile from `.env` when not exported."""
        write(env_dir / ".env", FLASK_ENV="testing")

        assert ConfigFactory.resolve_env() == "testing"

    def test_flask_env_is_case_insensitive(self, env_dir, monkeypatch):
        """Should normalise the profile name."""
        monkeypatch.setenv("FLASK_ENV", "Testing")

        assert ConfigFactory.resolve_env() == "testing"

    def test_defaults_to_development(self, env_dir):
        """Should fall back to development when nothing is configured."""
        assert ConfigFactory.resolve_env() == "development"

    def test_unknown_profile_is_rejected(self, env_dir):
        """Should raise a helpful error for an unknown profile."""
        with pytest.raises(ValueError, match="Unknown environment"):
            ConfigFactory.create_config("staging-2")


# ------------------------------------------------------------------
# TestTestingIsolation
# ------------------------------------------------------------------
class TestTestingIsolation:
    """Tests that the testing profile ignores the environment completely."""

    def test_ignores_dotenv_files(self, env_dir):
        """Should not read `.env` for the testing profile."""
        write(env_dir / ".env", BATCH_CREATE_LIMIT=1, LOGGER_TYPE="hacked")

        config = ConfigFactory.create_config("testing")

        assert config.BATCH_CREATE_LIMIT == MAX_BATCH_ITEMS
        assert config.LOGGER_TYPE == "auto"

    def test_ignores_exported_variables(self, env_dir, monkeypatch):
        """Should not read exported variables either."""
        monkeypatch.setenv("BATCH_CREATE_LIMIT", "777")
        monkeypatch.setenv("DATABASE_URL", "postgresql://somewhere/real")
        monkeypatch.setenv("CORS_ORIGINS", "https://evil.example")

        config = TestingConfig()

        assert config.BATCH_CREATE_LIMIT == MAX_BATCH_ITEMS
        assert config.DATABASE_URL == "sqlite:///:memory:"
        assert config.CORS_ORIGINS == ["http://localhost:5000"]

    def test_ignores_exported_pool_settings(self, env_dir, monkeypatch):
        """
        Should ignore the environment for the pool sizes too.

        They are the group ``BaseConfig`` declares as properties reading
        through ``read_env`` instead of as ``EnvField`` descriptors, and
        the descriptor is where ``IGNORE_ENV`` is obeyed -- so these three
        went on reading the machine. ``production`` and ``staging``
        declare their secrets the same way and are still blind to the
        flag; see the open decisions in docs/DEVELOPER_GUIDE.md. The
        subclass below is what
        ``tests/integration/docker/conftest.py`` builds: a detached profile
        that does run on PostgreSQL, which is the only shape in which the
        values are consulted at all.
        """
        monkeypatch.setenv("DATABASE_POOL_SIZE", "999")
        monkeypatch.setenv("DATABASE_MAX_OVERFLOW", "888")
        monkeypatch.setenv("DATABASE_POOL_RECYCLE", "777")

        class OnPostgres(TestingConfig):
            DATABASE_TYPE = "postgresql"

        config = OnPostgres()

        assert config.DATABASE_POOL_SIZE == 20
        assert config.DATABASE_MAX_OVERFLOW == 10
        assert config.DATABASE_POOL_RECYCLE == 3600

    def test_a_broken_exported_pool_setting_cannot_reach_it(
        self, env_dir, monkeypatch
    ):
        """
        Should not even parse the value, let alone fail on it.

        A non-numeric ``DATABASE_POOL_SIZE`` used to raise out of
        ``get_pool_params()`` and take the DI container down with it, on a
        profile that had promised to ignore the environment.
        """
        monkeypatch.setenv("DATABASE_POOL_SIZE", "not-a-number")

        class OnPostgres(TestingConfig):
            DATABASE_TYPE = "postgresql"

        assert OnPostgres().DATABASE_POOL_SIZE == 20

    def test_it_does_not_publish_dotenv_into_the_process(
        self, env_dir, monkeypatch
    ):
        """``NO_DOTENV_ENVS`` is what this class is named after, and only
        ``IGNORE_ENV`` was holding it up.

        Every other test here reads values back off the configuration,
        where the detachment answers first -- so removing ``testing`` from
        ``NO_DOTENV_ENVS`` leaves them all green. What the list actually
        prevents is the *side effect*: ``_apply_env_files`` writes into
        ``os.environ``, and those values outlive the call. A test run that
        published them would hand them to everything that reads the
        environment afterwards, subprocesses included -- alembic among
        them, which resolves its own database that way.

        The second half is the control: without it, a broken
        ``_apply_env_files`` that published nothing at all would pass.
        """
        write(env_dir / ".env", MARKER_FROM_DOTENV="published")
        # Registered through monkeypatch so the control below is undone
        # when the test ends; blank counts as unset, so it does not mask
        # the file.
        monkeypatch.setenv("MARKER_FROM_DOTENV", "")

        ConfigFactory.create_config("testing")

        assert os.environ["MARKER_FROM_DOTENV"] == ""

        ConfigFactory.create_config("development")

        assert os.environ["MARKER_FROM_DOTENV"] == "published"

    def test_survives_another_profile_loading_dotenv(self, env_dir):
        """
        Should stay isolated after a different profile pulled `.env` into
        os.environ earlier in the same process.
        """
        write(env_dir / ".env", BATCH_CREATE_LIMIT=1, GUEST_LINK_LIMIT=1)

        ConfigFactory.create_config("development")
        config = ConfigFactory.create_config("testing")

        assert config.BATCH_CREATE_LIMIT == MAX_BATCH_ITEMS
        assert config.GUEST_LINK_LIMIT == 10


# ------------------------------------------------------------------
# TestEnvFieldCasting
# ------------------------------------------------------------------
class TestEnvFieldCasting:
    """Tests for value conversion in the env descriptors."""

    class Probe:
        """Configuration-like holder used to exercise the descriptors."""
        TEXT: str = env_str("PROBE_TEXT", "fallback")
        NUMBER: int = env_int("PROBE_NUMBER", 42)
        RATIO: float = env_float("PROBE_RATIO", 1.5)
        FLAG: bool = env_bool("PROBE_FLAG", False)
        ITEMS: list = env_list("PROBE_ITEMS", ["a"])

    @pytest.fixture(autouse=True)
    def clean_probe_env(self, monkeypatch):
        for name in ("PROBE_TEXT", "PROBE_NUMBER", "PROBE_RATIO", "PROBE_FLAG", "PROBE_ITEMS"):
            monkeypatch.delenv(name, raising=False)

    def test_defaults(self):
        """Should return declared defaults when nothing is set."""
        assert self.Probe.TEXT == "fallback"
        assert self.Probe.NUMBER == 42
        assert self.Probe.FLAG is False
        assert self.Probe.ITEMS == ["a"]

    @pytest.mark.parametrize("raw", ["true", "TRUE", "1", "yes", "on", " True "])
    def test_truthy_values(self, monkeypatch, raw):
        """Should accept the documented true spellings."""
        monkeypatch.setenv("PROBE_FLAG", raw)

        assert self.Probe.FLAG is True

    @pytest.mark.parametrize("raw", ["false", "FALSE", "0", "no", "off"])
    def test_falsy_values(self, monkeypatch, raw):
        """Should accept the documented false spellings."""
        monkeypatch.setenv("PROBE_FLAG", raw)

        assert self.Probe.FLAG is False

    def test_typo_in_boolean_raises(self, monkeypatch):
        """Should refuse an unrecognised boolean instead of silently using False."""
        monkeypatch.setenv("PROBE_FLAG", "truthy")

        with pytest.raises(ValueError, match="PROBE_FLAG"):
            self.Probe.FLAG

    def test_invalid_number_raises(self, monkeypatch):
        """Should report the offending variable by name."""
        monkeypatch.setenv("PROBE_NUMBER", "not-a-number")

        with pytest.raises(ValueError, match="PROBE_NUMBER"):
            self.Probe.NUMBER

    @pytest.mark.parametrize("raw", ["", "   "])
    def test_blank_value_is_treated_as_unset(self, monkeypatch, raw):
        """
        Should fall back to the default for a blank value.

        docker compose substitutes an empty string for every ${VAR} missing
        from the env file, so a blank must not become a crash or an empty
        setting.
        """
        monkeypatch.setenv("PROBE_NUMBER", raw)
        monkeypatch.setenv("PROBE_TEXT", raw)

        assert self.Probe.NUMBER == 42
        assert self.Probe.TEXT == "fallback"

    def test_list_parsing(self, monkeypatch):
        """Should split on commas and drop blank items."""
        monkeypatch.setenv("PROBE_ITEMS", "x, y ,, z,")

        assert self.Probe.ITEMS == ["x", "y", "z"]

    def test_value_is_read_on_every_access(self, monkeypatch):
        """Should never cache: `.env` may be loaded after import."""
        monkeypatch.setenv("PROBE_NUMBER", "1")
        assert self.Probe.NUMBER == 1

        monkeypatch.setenv("PROBE_NUMBER", "2")
        assert self.Probe.NUMBER == 2


# ------------------------------------------------------------------
# TestFlaskConfigIntegration
# ------------------------------------------------------------------
class TestTheSuiteCannotReachARealDatabase:
    """These tests build a real app; it must not be pointed anywhere real.

    The `development` profile reads the environment, and application
    startup seeds roles -- so an exported ``DATABASE_*`` set was enough for
    this file to connect to a developer's or CI runner's own database and
    write into it, while reporting success.
    """

    @pytest.mark.parametrize(
        "name, value",
        [
            ("DATABASE_TYPE", "postgresql"),
            ("DATABASE_NAME", "production_db"),
            ("DATABASE_HOST", "db.internal.example"),
            ("DATABASE_USER", "produser"),
            ("DATABASE_PASSWORD", "prodsecret"),
            ("DATABASE_URL", "postgresql://prod/real"),
        ],
    )
    def test_exported_database_settings_do_not_survive(
        self, name, value, monkeypatch, tmp_path
    ):
        """Each of these once decided where the suite connected."""
        monkeypatch.setenv(name, value)

        # Enter the fixture only after the variable is set, so it has
        # something to scrub.
        monkeypatch.chdir(tmp_path)
        # And point the root at it as well: `_read_env_file` reads the
        # project root before it walks up from here, and that root is
        # derived from the configuration module's own location -- so
        # without this line the scrubbing above is undone by the
        # developer's real `.env`, which is exactly what this class exists
        # to prevent. Measured before it was added: a `.env` naming a
        # PostgreSQL host built a URL against that host, with its user and
        # password in it, right here -- and five of the six
        # parametrisations still passed, because each only checks that
        # *its own* value is absent from the URL.
        monkeypatch.setattr(factory_module, "PROJECT_ROOT", tmp_path)
        for scrubbed in SCRUBBED_NAMES:
            monkeypatch.delenv(scrubbed, raising=False)
        for present in list(os.environ):
            if present.startswith(SCRUBBED_PREFIXES):
                monkeypatch.delenv(present, raising=False)

        assert os.environ.get(name) is None

        url = ConfigFactory.create_config("development").get_database_url()
        assert value not in url

    def test_no_file_on_this_machine_can_point_the_suite_anywhere(
        self, monkeypatch, tmp_path
    ):
        """The gap the six parametrisations above cannot see.

        Each of them asserts only that its own value is missing from the
        URL, so a `.env` naming a completely different database passes all
        six. This one asserts the whole URL against a literal instead.
        """
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(factory_module, "PROJECT_ROOT", tmp_path)
        for scrubbed in SCRUBBED_NAMES:
            monkeypatch.delenv(scrubbed, raising=False)
        for present in list(os.environ):
            if present.startswith(SCRUBBED_PREFIXES):
                monkeypatch.delenv(present, raising=False)

        url = ConfigFactory.create_config("development").get_database_url()

        assert url.startswith("sqlite:///")
        assert "postgresql" not in url
        assert "@" not in url


class TestFlaskConfigIntegration:
    """Tests that resolved values reach Flask's own config mapping."""

    def test_app_config_holds_values_not_descriptors(self, env_dir, monkeypatch):
        """Should expose plain values in app.config, correctly typed."""
        from link_shortener.web.app_factory import create_app

        monkeypatch.setenv("PORT", "6001")
        monkeypatch.setenv("CORS_ORIGINS", "https://a.example,https://b.example")

        app = create_app(config=ConfigFactory.create_config("development"))
        try:
            assert app.config["PORT"] == 6001
            assert app.config["CORS_ORIGINS"] == [
                "https://a.example", "https://b.example"
            ]
            assert not any(
                isinstance(value, EnvField) for value in app.config.values()
            )
        finally:
            app.container.close()

    def test_generated_secrets_do_not_leak_into_app_config(self, env_dir):
        """Should keep the randomly generated fallbacks out of app.config."""
        config = ConfigFactory.create_config("development")

        exported = {key for key in dir(config) if key.isupper()}

        assert "_DEFAULT_SECRET_KEY" not in exported
        assert "_DEFAULT_PEPPER" not in exported


# ------------------------------------------------------------------
# TestNoDirectEnvReads
# ------------------------------------------------------------------
class TestNoDirectEnvReads:
    """Guards the rule that configuration classes never read env eagerly."""

    def test_config_class_bodies_do_not_call_os_environ(self):
        """
        Should keep `os.environ` out of class bodies in the config packages.

        A read in a class body happens at import time, before `.env` is
        loaded, so the value from the file would be silently ignored.
        """
        import ast
        import pathlib

        import link_shortener.infrastructure.configs as configs_pkg

        offenders = []
        root = pathlib.Path(configs_pkg.__file__).parent
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                for stmt in node.body:
                    # Statements inside methods are fine: they are lazy already.
                    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    for sub in ast.walk(stmt):
                        if (
                            isinstance(sub, ast.Attribute)
                            and sub.attr == "environ"
                            and isinstance(sub.value, ast.Name)
                            and sub.value.id == "os"
                        ):
                            offenders.append(f"{path.name}:{node.name}")

        assert offenders == []
