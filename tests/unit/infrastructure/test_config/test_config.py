from link_shortener.infrastructure.config.development import DevelopmentConfig
from link_shortener.infrastructure.config.factory import ConfigFactory
from link_shortener.infrastructure.config.production import ProductionConfig
from link_shortener.infrastructure.config.staging import StagingConfig
from link_shortener.infrastructure.config.testing import TestingConfig
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

        # Запрет на загрузку переменных из .env файла
        mocker.patch(
            'link_shortener.infrastructure.config.factory.load_dotenv', 
            return_value=None
        )

        # Убедимся, что обязательные переменные отсутствуют
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

