import os

from dotenv import load_dotenv

from link_shortener.infrastructure.config.base import BaseConfig
from link_shortener.infrastructure.config.development import DevelopmentConfig
from link_shortener.infrastructure.config.production import ProductionConfig
from link_shortener.infrastructure.config.staging import StagingConfig
from link_shortener.infrastructure.config.testing import TestingConfig


class ConfigFactory:
    """
    Factory for creating configuration objects 
        based on environment name.
    """

    CONFIG_MAP = {
        "development": DevelopmentConfig,
        "staging": StagingConfig,
        "production": ProductionConfig,
        "testing": TestingConfig,
    }

    @classmethod
    def create_config(cls, env: str = None) -> BaseConfig:
        """
        Create a configuration instance for the given environment.

        If env is None, it reads from FLASK_ENV environment variable (default "development").
        It also loads environment variables from a .env.{env} file if it exists,
        falling back to .env.

        Args:
            env: Environment name (development, staging, production, testing).

        Returns:
            An instance of the appropriate configuration class.

        Raises:
            ValueError: If the environment name is unknown.
        """

        if env is None:
            env = os.environ.get("FLASK_ENV", "development").lower()

        # Загрузка переменных окружения из .env.{env} или .env
        env_file = f".env.{env}"
        if os.path.exists(env_file):
            load_dotenv(env_file)
        elif os.path.exists(".env"):
            load_dotenv()

        # Получение класса конфигурации
        config_class = cls.CONFIG_MAP.get(env)
        if not config_class:
            raise ValueError(
                f"Unknown environment: {env}",
                f"Avalibles: {list(cls.CONFIG_MAP.keys())}",
            )

        # Создание экземпляра
        config = config_class()

        # Валидация
        config.validate()
        return config


def get_config(env: str = None) -> BaseConfig:
    """Convenience function to get configuration."""
    return ConfigFactory.create_config(env)
