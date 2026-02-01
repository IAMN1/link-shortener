import logging

from link_shortener.infrastructure.config.base import BaseConfig



class StagingConfig(BaseConfig):
    DEBUG: bool = False

    # ========== logging settings ==========
    LOG_LEVEL: int = logging.INFO
    LOG_TO_CONSOLE: bool = False
    LOG_TO_FILE: bool = True
    LOG_DIR: str = '/var/log/link_shortener/staging'

    # ========== Security App ==========
    # SECRET_KEY - должен быть установлен через переменные окружения

    # ========== Database settings ==========
    # DATABASE_URL - должен быть установлен через переменные окружения

    # ========== Redis cache settings ==========
    REDIS_ENABLED: bool = True
    REDIS_CACHE_TTL: int = 12 * 60 * 60 # 12h for staging

    # ========== Limits ==========
    MAX_REQUESTS_PER_MINUTE: int = 200
    BATCH_CREATE_LIMIT: int = 100