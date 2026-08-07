from link_shortener.infrastructure.configs.app.base import (
    BaseConfig, MAX_BATCH_ITEMS
)


class TestingConfig(BaseConfig):
    """
    Configuration for automated testing (pytest).
    Uses in-memory SQLite database, disables most external services,
    and provides dummy secrets.

    The whole class is detached from the environment (see ``IGNORE_ENV``):
    a test run must produce the same result on a developer laptop and in CI,
    regardless of what happens to be exported in the shell or written in a
    local ``.env``. Tests that need a different value subclass this config and
    override the attribute directly – see ``tests/integration/conftest.py``.
    """

    IGNORE_ENV: bool = True

    TESTING: bool = True
    DEBUG: bool = False


    # --------------------------------------------------------------------------
    # Dummy secrets for testing
    # --------------------------------------------------------------------------
    SECRET_KEY: str = "test-secret-key"
    SHORT_CODE_SECRET_PEPPER: str = "test-pepper"


    # --------------------------------------------------------------------------
    # Batch limit: the ceiling itself
    # --------------------------------------------------------------------------
    BATCH_CREATE_LIMIT: int = MAX_BATCH_ITEMS
    """Was 200, which the request schema refused at 101 anyway.

    A test written against 200 measured the schema's message, not this
    setting -- and the profile that sets it is the one the suite runs on.
    """


    # --------------------------------------------------------------------------
    # Alembic: disabled in tests for faster setup (use create_all directly)
    # --------------------------------------------------------------------------
    USE_ALEMBIC: bool = False


    # --------------------------------------------------------------------------
    # Database: always SQLite in-memory for tests
    # --------------------------------------------------------------------------
    DATABASE_URL: str = "sqlite:///:memory:"

    @property
    def DATABASE_TYPE(self) -> str:
        return "sqlite"


    # --------------------------------------------------------------------------
    # Redis: disabled
    # --------------------------------------------------------------------------
    REDIS_ENABLED: bool = False
    REDIS_URL: str = (
        "redis://localhost:6379/0"  # Not used in tests, but defined for completeness.
    )


    # --------------------------------------------------------------------------
    # Auto-seed roles: enabled for convenience in tests
    # --------------------------------------------------------------------------
    AUTO_SEED_ROLES: bool = True
