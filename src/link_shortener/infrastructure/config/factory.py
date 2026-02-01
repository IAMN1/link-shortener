from dotenv import load_dotenv

from link_shortener.infrastructure.config.base import BaseConfig
from .production import ProductionConfig
from .staging import StagingConfig
from .development import DevelopmentConfig
from .testing import TestingConfig
import os


class ConfigFactory:
    """Фабрика для инициализации конфигурации"""

    CONFIG_MAP = {
        'development': DevelopmentConfig,
        'testing': TestingConfig,
        'staging': StagingConfig,
        'production': ProductionConfig
    }

    @classmethod
    def create_config(cls, env: str = None) -> BaseConfig:
        """
        Метод создания конфигурации на основе окружения

        Args:
            env (str, optional): Имя окружения (development, testing, staging, production). Defaults to None.

        Returns:
            BaseConfig: Экземпляр класса конфигурации
        """

        if env is None:
            env = os.environ.get('FLASK_ENV', 'development').lower()
        
        env_file = f'.env.{env}'
        if os.path.exists(env_file):
            load_dotenv(env_file)
        elif os.path.exists('.env'):
            load_dotenv()
        

        config_class = cls.CONFIG_MAP.get(env)
        if not config_class:
            raise ValueError(
                f'Неизвестное окружение: {env}.'
                f'Доступные окружения: {list(cls.CONFIG_MAP.keys())}'
            )
        
        # Создаем экземпляр конфигурации
        config = config_class()

        # Загрузка переменных окружения в конфигурацию
        cls._load_environment_vars(config)


        return config
    
    @staticmethod
    def _load_environment_vars(config: BaseConfig) -> None:
        """
        Метод загрузки переменных окружения в объект конфигурации
        """

        for attr_name in dir(config):
            # пропуск приватных атрибутов и методов
            if attr_name.startswith('_') or callable(getattr(config, attr_name)):
                continue

            # проверка есть ли переменные окружения с такими же именами
            env_value = os.environ.get(attr_name)
            if env_value is not None:
                # преобразование типа
                current_value = getattr(config, attr_name)
                if isinstance(current_value, bool):
                    pass
                elif isinstance(current_value, int):
                    try:
                        setattr(config, attr_name, int(env_value))
                    except ValueError:
                        pass # оставляем занчение по умолчанию
                else:
                    setattr(config, attr_name, env_value)
    
def get_config(env: str = None) -> BaseConfig:
    """
    Фабричный метод для получения конфигурации

    Args:
        env (str, optional): имя окружения (опционально). Defaults to None.

    Returns:
        BaseConfig: Объект конфигурации
    """
    return ConfigFactory.create_config(env)


