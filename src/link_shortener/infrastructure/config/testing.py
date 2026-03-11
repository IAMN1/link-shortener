import os

from link_shortener.infrastructure.config.base import BaseConfig


class TestingConfig(BaseConfig):
    """Configuration for testing environment."""

    TESTING: bool = True
    DEBUG: bool = False

    # ========== Security App ==========
    SECRET_KEY: str = "test-secret-key"
    SHORT_CODE_SECRET_PEPPER: str = "test-pepper"

    # ========== Limits ==========
    MAX_REQUESTS_PER_MINUTE: int = int(os.environ.get("MAX_REQUESTS_PER_MINUTE", 1000))
    BATCH_CREATE_LIMIT: int = int(os.environ.get("BATCH_CREATE_LIMIT", 200))

    # ========== Database settings ==========
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///:memory:")

    # ========== Redis cache settings ==========
    REDIS_ENABLED: bool = False
    REDIS_URL: str = (
        "redis://localhost:6379/0"  # не используется, но определена (пока что)
    )
