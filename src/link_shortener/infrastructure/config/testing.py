import logging
import os

from link_shortener.infrastructure.config.base import BaseConfig



class TestingConfig(BaseConfig):
    TESTING: bool = True
    DEBUG: bool = False

    # ========== logging settings ==========
    LOG_LEVEL: int = logging.WARNING
    LOG_TO_CONSOLE: bool = False
    LOG_TO_FILE: bool = False

    # ========== Security App ==========
    SECRET_KEY: str = 'test-secret-key'

    # ========== Limits ==========
    MAX_REQUESTS_PER_MINUTE: int = 1000
    BATCH_CREATE_LIMIT: int = 200
    
    # ========== Database settings ==========
    DATABASE_URL: str = os.environ.get('DATABASE_URL', 'sqlite:///test.db')

    # ========== Redis cache settings ==========
    REDIS_ENABLED: bool = False