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
        Create a configuration object for the given environment.

        Args:
            env: Environment name (development, staging, production, testing).
                 If None, reads from FLASK_ENV environment variable (default: development).

        Returns:
            Configuration instance.

        Raises:
            ValueError: If environment is unknown.
        """

        if env is None:
            env = os.environ.get("FLASK_ENV", "development").lower()

        # Load base .env if exists
        if os.path.exists(".env"):
            load_dotenv(".env")

        # Load environment-specific .env.{env} if exists (overrides)
        env_file = f".env.{env}"
        if os.path.exists(env_file):
            load_dotenv(env_file, override=True)

        config_class = cls.CONFIG_MAP.get(env)
        if not config_class:
            raise ValueError(f"Unknown environment: {env}")

        config = config_class()
        config.validate()
        return config


def get_config(env: str = None) -> BaseConfig:
    """Convenience function to get configuration."""
    return ConfigFactory.create_config(env)
