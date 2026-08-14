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
    """The ceiling itself, so a test written against this setting
    measures the setting and not the request schema's own refusal.
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


    # --------------------------------------------------------------------------
    # Mail: never sent from a test run
    # --------------------------------------------------------------------------
    MAIL_ENABLED: bool = False
    """Stated here rather than inherited, and the difference is the point.

    ``IGNORE_ENV`` already detaches the field from the machine, so the base
    default would reach the suite unchanged today. What it would not
    survive is that default changing: the day mail is switched on for
    everyone, a test run would start opening sockets to whatever
    ``MAIL_HOST`` resolves to. A plain attribute shadows the descriptor and
    cannot be turned on by any environment.
    """
