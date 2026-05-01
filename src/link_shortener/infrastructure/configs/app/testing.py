import os

from link_shortener.infrastructure.configs.app.base import BaseConfig


class TestingConfig(BaseConfig):
    """
    Configuration for automated testing (pytest).
    Uses in-memory SQLite database, disables most external services,
    and provides dummy secrets.
    """

    TESTING: bool = True
    DEBUG: bool = False


    # --------------------------------------------------------------------------
    # Dummy secrets for testing
    # --------------------------------------------------------------------------
    SECRET_KEY: str = "test-secret-key"
    SHORT_CODE_SECRET_PEPPER: str = "test-pepper"


    # --------------------------------------------------------------------------
    # Higher batch limit for test scenarios
    # --------------------------------------------------------------------------
    BATCH_CREATE_LIMIT: int = int(os.environ.get("BATCH_CREATE_LIMIT", 200))


    # --------------------------------------------------------------------------
    # Alembic: disabled in tests for faster setup (use create_all directly)
    # --------------------------------------------------------------------------
    USE_ALEMBIC: bool = False


    # --------------------------------------------------------------------------
    # Database: in-memory SQLite for fast isolated tests
    # --------------------------------------------------------------------------
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///:memory:")


    # --------------------------------------------------------------------------
    # Redis: disabled
    # --------------------------------------------------------------------------
    REDIS_ENABLED: bool = False
    REDIS_URL: str = (
        "redis://localhost:6379/0"  # не используется, но определена (пока что)
    )


    # --------------------------------------------------------------------------
    # Auto-seed roles: enabled for convenience in tests
    # --------------------------------------------------------------------------
    AUTO_SEED_ROLES: bool = True
