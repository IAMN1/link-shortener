from link_shortener.infrastructure.configs.app.development import DevelopmentConfig
from link_shortener.infrastructure.configs.app.factory import ConfigFactory
from link_shortener.infrastructure.configs.app.production import ProductionConfig
from link_shortener.infrastructure.configs.app.staging import StagingConfig
from link_shortener.infrastructure.configs.app.testing import TestingConfig
import pytest


# Every test here builds a profile that reads `.env`, and `find_dotenv`
# searches upwards from the working directory -- from the repository root
# that is the developer's own file. Without this the results of the module
# depend on a file that is not in the repository, and the values it carries
# outlive the test that read them (see tests/conftest.py).
pytestmark = pytest.mark.usefixtures("detached_env")


# ------------------------------------------------------------------
# TestConfigFactory
# ------------------------------------------------------------------
class TestConfigFactory:
    """Tests for ConfigFactory."""

    def test_create_development_config(self, monkeypatch):
        """Should create DevelopmentConfig when FLASK_ENV=development."""

        # Arrange
        monkeypatch.setenv("FLASK_ENV", "development")

        # Act
        config = ConfigFactory.create_config()

        # Assert
        assert isinstance(config, DevelopmentConfig)
        assert config.DEBUG is True


    def test_create_production_config(self, monkeypatch):
        """
        Should create ProductionConfig
        when FLASK_ENV=production with required env vars.
        """

        # Arrange
        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv("SECRET_KEY", "prod-secret")
        monkeypatch.setenv("SHORT_CODE_PEPPER", "prod-pepper")
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("DOMAIN", "example.com")

        # Act
        config = ConfigFactory.create_config()
        assert isinstance(config, ProductionConfig)
        assert config.DEBUG is False
        assert config.SECRET_KEY == "prod-secret"

    def test_validate_production_missing_vars(self, monkeypatch, mocker):
        """
        Should raise ValueError in production
        when required env vars are missing.
        """

        monkeypatch.setenv('FLASK_ENV', 'production')

        # Prevent loading variables from .env files: a developer machine may
        # well have a .env with SECRET_KEY in it, and the point of this test is
        # the behaviour when nothing is configured.
        mocker.patch.object(
            ConfigFactory, '_apply_env_files', return_value=None
        )

        # Ensure required variables are absent
        monkeypatch.delenv('SECRET_KEY', raising=False)
        monkeypatch.delenv('SHORT_CODE_PEPPER', raising=False)
        monkeypatch.delenv('DATABASE_URL', raising=False)
        monkeypatch.delenv('REDIS_URL', raising=False)

        with pytest.raises(ValueError, match='SECRET_KEY|SHORT_CODE_PEPPER|DATABASE_URL|REDIS_URL'):
            ConfigFactory.create_config()


    def test_create_testing_config(self):
        """Should create TestingConfig when env='testing'."""

        # Act
        config = ConfigFactory.create_config("testing")

        # Assert
        assert isinstance(config, TestingConfig)
        assert config.DEBUG is False


    def test_create_staging_config(self, monkeypatch):
        """
        Should create StagingConfig
        when FLASK_ENV=staging with required env vars.
        """

        # Arrange
        monkeypatch.setenv("FLASK_ENV", "staging")
        monkeypatch.setenv("SECRET_KEY", "staging-secret")
        monkeypatch.setenv("SHORT_CODE_PEPPER", "staging-pepper")
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@staging/db")
        monkeypatch.setenv("REDIS_URL", "redis://staging:6379/0")
        # Demanded since the profile gained a validate() of its own, on the
        # same terms as production: without it BASE_URL falls back to the
        # bind address and every short link names an internal host.
        monkeypatch.setenv("DOMAIN", "staging.example.com")

        # Act
        config = ConfigFactory.create_config()

        # Assert
        assert isinstance(config, StagingConfig)
        assert config.DEBUG is False
        assert config.TESTING is False
        assert config.SECRET_KEY == "staging-secret"


    def test_base_url_property(self, monkeypatch):
        """Should generate correct BASE_URL based on environment."""

        # Arrange
        monkeypatch.setenv("FLASK_ENV", "development")

        # Act
        config = ConfigFactory.create_config()

        # Assert
        # Compared against a literal rather than against
        # f"http://{config.HOST}:{config.PORT}/". Built from the same object,
        # the expectation restates the implementation and holds whatever HOST
        # and PORT turn out to be -- and it stood here for a while without an
        # `assert` at all, quietly checking nothing either way.
        assert config.BASE_URL == "http://localhost:5000/"

        # Again with HOST and PORT off their defaults. The line above pins
        # what the defaults are; this one pins that BASE_URL is built from
        # the two settings at all. A BASE_URL returning the default string
        # outright satisfied the first assertion and the whole suite.
        monkeypatch.setenv("HOST", "example.test")
        monkeypatch.setenv("PORT", "8080")
        config = ConfigFactory.create_config()
        assert config.BASE_URL == "http://example.test:8080/"
        monkeypatch.delenv("HOST")
        monkeypatch.delenv("PORT")

        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv("DOMAIN", "test.com")
        monkeypatch.setenv("USE_HTTPS", "true")
        monkeypatch.setenv("SECRET_KEY", "key")
        monkeypatch.setenv("SHORT_CODE_PEPPER", "pepper")
        monkeypatch.setenv("DATABASE_URL", "postgresql://...")
        monkeypatch.setenv("REDIS_URL", "redis://...")
        config = ConfigFactory.create_config()
        assert config.BASE_URL == "https://test.com"

        # And that USE_HTTPS is what decides the scheme. Without this, a
        # BASE_URL hard-coding https satisfies the line above -- a service
        # behind plain HTTP would then hand out https:// short links.
        monkeypatch.setenv("USE_HTTPS", "false")
        config = ConfigFactory.create_config()
        assert config.BASE_URL == "http://test.com"

    def test_database_type_reads_from_env(self, monkeypatch):
        """DATABASE_TYPE property should read from env at runtime."""
        monkeypatch.setenv("DATABASE_TYPE", "postgresql")
        config = DevelopmentConfig()
        assert config.DATABASE_TYPE == "postgresql"
        monkeypatch.setenv("DATABASE_TYPE", "sqlite")
        config = DevelopmentConfig()
        assert config.DATABASE_TYPE == "sqlite"

    def test_development_config_echo_from_env(self, monkeypatch):
        """DevelopmentConfig.SQLALCHEMY_ECHO should read from env."""
        monkeypatch.setenv("SQLALCHEMY_ECHO", "true")
        config = DevelopmentConfig()
        assert config.SQLALCHEMY_ECHO is True
        monkeypatch.setenv("SQLALCHEMY_ECHO", "false")
        config = DevelopmentConfig()
        assert config.SQLALCHEMY_ECHO is False

    def test_development_config_seed_from_env(self, monkeypatch):
        """DevelopmentConfig.AUTO_SEED_ROLES should read from env."""
        monkeypatch.setenv("AUTO_SEED_ROLES", "false")
        config = DevelopmentConfig()
        assert config.AUTO_SEED_ROLES is False
        monkeypatch.setenv("AUTO_SEED_ROLES", "true")
        config = DevelopmentConfig()
        assert config.AUTO_SEED_ROLES is True

    def test_production_config_cookie_security(self, monkeypatch, tmp_path):
        """ProductionConfig should enforce secure cookie settings.

        Run from an empty directory on purpose. The ``production`` profile
        reads ``.env``, and ``.env.example`` -- which the quick start tells
        you to copy -- sets ``SESSION_COOKIE_SECURE=false`` for local work
        without TLS. So this passed for whoever wrote it, whose ``.env``
        happened not to carry that key, and failed on a fresh clone that
        followed the instructions. What is under test is the profile's own
        rule, not the profile plus whatever the machine has lying around.
        """
        # Redundant since the module opted into `detached_env`, which enters
        # an empty directory and removes these anyway. Kept on purpose: this
        # test is the one that broke, and it should not depend on a
        # module-level mark staying where it is.
        monkeypatch.chdir(tmp_path)
        for name in (
            "SESSION_COOKIE_SECURE", "SESSION_COOKIE_HTTPONLY",
            "SESSION_COOKIE_SAMESITE", "COOKIE_SECURE",
        ):
            monkeypatch.delenv(name, raising=False)

        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv("SECRET_KEY", "prod-key")
        monkeypatch.setenv("SHORT_CODE_PEPPER", "prod-pepper")
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("DOMAIN", "example.com")
        config = ConfigFactory.create_config()
        assert config.SESSION_COOKIE_SECURE is True
        assert config.SESSION_COOKIE_SAMESITE == "Lax"
        assert config.SESSION_COOKIE_HTTPONLY is True

    def test_testing_config_uses_sqlite(self):
        """TestingConfig should always use SQLite."""
        config = TestingConfig()
        assert config.DATABASE_TYPE == "sqlite"
        assert config.DATABASE_URL == "sqlite:///:memory:"
