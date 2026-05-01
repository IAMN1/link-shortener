import os

from link_shortener.infrastructure.configs.app.base import BaseConfig


class StagingConfig(BaseConfig):
    """
    Configuration for staging (pre-production) environment.
    Should closely mirror production settings but with debugging disabled.
    Secrets must be provided via environment variables.
    """

    DEBUG: bool = False
    TESTING: bool = False


    # --------------------------------------------------------------------------
    # Logging: typically more verbose than production for debugging
    # --------------------------------------------------------------------------
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
    LOG_TO_CONSOLE: bool = os.environ.get("LOG_TO_CONSOLE", "false").lower() == "true"
    LOG_TO_FILE: bool = os.environ.get("LOG_TO_FILE", "true").lower() == "true"
    LOG_DIR: str = os.environ.get("LOG_DIR", "/var/log/link_shortener/staging")


    # --------------------------------------------------------------------------
    # Security: enforce presence of secrets
    # --------------------------------------------------------------------------
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


    # --------------------------------------------------------------------------
    # Redis: enabled by default for realistic testing
    # --------------------------------------------------------------------------
    REDIS_ENABLED: bool = os.environ.get("REDIS_ENABLED", "true").lower() == "true"
    
    @property
    def REDIS_URL(self) -> str:
        """Redis URL must be set in environment if Redis is enabled."""
        url = os.environ.get("REDIS_URL")
        if self.REDIS_ENABLED and not url:
            raise ValueError("REDIS_URL must be set in environment when REDIS_ENABLED=True")
        return url or "redis://localhost:6379/0"


    # --------------------------------------------------------------------------
    # Limits: same as production
    # --------------------------------------------------------------------------
    BATCH_CREATE_LIMIT: int = int(os.environ.get("BATCH_CREATE_LIMIT", 100))


    # --------------------------------------------------------------------------
    # Auto-seed roles: disabled (use migrations instead)
    # --------------------------------------------------------------------------
    AUTO_SEED_ROLES: bool = False
    """
    In staging, we rely on migrations to set up roles, not automatic seeding.
    """


    # --------------------------------------------------------------------------
    # Alembic: must be enabled in staging (mirrors production)
    # --------------------------------------------------------------------------
    USE_ALEMBIC: bool = True
