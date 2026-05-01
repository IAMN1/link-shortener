import os

from link_shortener.infrastructure.configs.app.base import BaseConfig


class DevelopmentConfig(BaseConfig):
    """
    Configuration for local development environment.
    Optimized for developer convenience: debugging enabled, shorter cache TTLs,
    in-memory cache by default, and auto-seeding of roles.
    """

    DEBUG: bool = True
    TESTING: bool = False


    # --------------------------------------------------------------------------
    # Cache: shorter TTLs for faster feedback during development
    # --------------------------------------------------------------------------
    CACHE_LINK_TTL: int = int(os.environ.get("CACHE_LINK_TTL", 20))
    CACHE_STATS_TTL: int = int(os.environ.get("CACHE_STATS_TTL", 20))


    # --------------------------------------------------------------------------
    # Redis: disabled by default for simpler local setup (use in-memory cache)
    # --------------------------------------------------------------------------
    REDIS_ENABLED: bool = os.environ.get("REDIS_ENABLED", "false").lower() == "true"
    REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


    # --------------------------------------------------------------------------
    # Alembic: enabled by default for consistency, but can be overridden
    # --------------------------------------------------------------------------
    USE_ALEMBIC: bool = os.environ.get("USE_ALEMBIC", "true").lower() == "true"


    # --------------------------------------------------------------------------
    # Database: echo SQL for debugging
    # --------------------------------------------------------------------------
    SQLALCHEMY_ECHO: bool = True
    """
    Log all SQL queries – helpful for development.
    """


    # --------------------------------------------------------------------------
    # Auto-seed roles at startup (safe and convenient)
    # --------------------------------------------------------------------------
    AUTO_SEED_ROLES: bool = True
    """
    Automatically ensure base roles exist on every startup.
    """
