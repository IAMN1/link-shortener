import logging
import os

from link_shortener.infrastructure.config.base import BaseConfig



class DevelopmentConfig(BaseConfig):
    DEBUG: bool = True
    
    # ========== Logging settings ==========
    LOG_LEVEL: int = logging.DEBUG
    LOG_TO_CONSOLE: bool= True
    LOG_TO_FILE: bool = False

    # ========== Security App ==========
    #SECRET_KEY: str = "dev-secret-key-change-in-production"
    
    # ========== Database settings ==========
    DATABASE_URL: str = os.environ.get('DATABASE_URL_TEST', 'sqlite:///dev.db')

    # ========== Redis cache settings ==========
    REDIS_ENABLED: bool = os.environ.get('REDIS_ENABLED', False)
    REDIS_URL: str = os.environ.get('redis://localhost:6379/0', '-')
