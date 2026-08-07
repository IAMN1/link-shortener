from link_shortener.infrastructure.configs.app.development import DevelopmentConfig
from link_shortener.infrastructure.configs.app.factory import ConfigFactory
from link_shortener.infrastructure.configs.app.production import ProductionConfig
from link_shortener.infrastructure.configs.app.staging import StagingConfig
from link_shortener.infrastructure.configs.app.testing import TestingConfig
import pytest



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
        config.BASE_URL == f"http://{config.HOST}:{config.PORT}/"

        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv("DOMAIN", "test.com")
        monkeypatch.setenv("USE_HTTPS", "true")
        monkeypatch.setenv("SECRET_KEY", "key")
        monkeypatch.setenv("SHORT_CODE_PEPPER", "pepper")
        monkeypatch.setenv("DATABASE_URL", "postgresql://...")
        monkeypatch.setenv("REDIS_URL", "redis://...")
        config = ConfigFactory.create_config()
        assert config.BASE_URL == "https://test.com"

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

    def test_production_config_cookie_security(self, monkeypatch):
        """ProductionConfig should enforce secure cookie settings."""
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

