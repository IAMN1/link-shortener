import logging
import os

from link_shortener.infrastructure.config.base import BaseConfig


class StagingConfig(BaseConfig):
    """Configuration for staging environment (pre-production)."""

    DEBUG: bool = False
    TESTING: bool = False

    # ========== logging settings ==========
    LOG_LEVEL: int = logging.INFO
    LOG_TO_CONSOLE: bool = False
    LOG_TO_FILE: bool = True
    LOG_DIR: str = os.environ.get("LOG_DIR", "/var/log/link_shortener/staging")

    # ========== Security App ==========
    @property
    def SECRET_KEY(self) -> str:
        key = os.environ.get("SECRET_KEY")
        if not key:
            raise ValueError("SECRET_KEY must be set in environment")
        return key

    @property
    def SHORT_CODE_SECRET_PEPPER(self) -> str:
        pepper = os.environ.get("SHORT_CODE_PEPPER")
        if not pepper:
            raise ValueError("SHORT_CODE_PEPPER must be set in environment")
        return pepper

    # ========== Database settings ==========
    @property
    def DATABASE_URL(self) -> str:
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise ValueError("DATABASE_URL must be set in environment")
        return url

    # ========== Redis cache settings ==========
    REDIS_ENABLED: bool = os.environ.get("REDIS_ENABLED", "true").lower() == "true"
    REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    # ========== Limits ==========
    MAX_REQUESTS_PER_MINUTE: int = int(os.environ.get("MAX_REQUESTS_PER_MINUTE", 200))
    BATCH_CREATE_LIMIT: int = int(os.environ.get("BATCH_CREATE_LIMIT", 100))
