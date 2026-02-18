import os

from dotenv import load_dotenv

from link_shortener.infrastructure.config.base import BaseConfig
from link_shortener.infrastructure.config.development import DevelopmentConfig
from link_shortener.infrastructure.config.production import ProductionConfig
from link_shortener.infrastructure.config.staging import StagingConfig
from link_shortener.infrastructure.config.testing import TestingConfig


class ConfigFactory:
    """Фабрика конфигураций"""

    CONFIG_MAP = {
        "development": DevelopmentConfig,
        "staging": StagingConfig,
        "production": ProductionConfig,
        "testing": TestingConfig,
    }

    @classmethod
    def create_config(cls, env: str = None) -> BaseConfig:
        """Создание конфигурации по окружению"""

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
    """Получение конфигурации"""
    return ConfigFactory.create_config(env)
