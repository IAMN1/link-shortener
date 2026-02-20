import logging
import os

from link_shortener.infrastructure.config.base import BaseConfig


class DevelopmentConfig(BaseConfig):
    """Configuration for development environment."""

    DEBUG: bool = True
    TESTING: bool = False

    # ========== Logging settings ==========
    LOG_LEVEL: int = logging.DEBUG
    LOG_TO_CONSOLE: bool = True
    LOG_TO_FILE: bool = False

    # ========== Database settings ==========
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///dev.db")

    # ========== Redis cache settings ==========
    REDIS_ENABLED: bool = os.environ.get("REDIS_ENABLED", "false").lower() == "true"
    REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
