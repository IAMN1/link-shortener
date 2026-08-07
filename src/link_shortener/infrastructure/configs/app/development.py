from link_shortener.infrastructure.configs.app.base import BaseConfig
from link_shortener.infrastructure.configs.app.env import env_bool, env_int, env_str


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
    CACHE_LINK_TTL: int = env_int("CACHE_LINK_TTL", 20)
    CACHE_STATS_TTL: int = env_int("CACHE_STATS_TTL", 20)


    # --------------------------------------------------------------------------
    # Redis: disabled by default for simpler local setup (use in-memory cache)
    # --------------------------------------------------------------------------
    REDIS_ENABLED: bool = env_bool("REDIS_ENABLED", False)
    REDIS_URL: str = env_str("REDIS_URL", "redis://localhost:6379/0")


    # --------------------------------------------------------------------------
    # Alembic: enabled by default for consistency, but can be overridden
    # --------------------------------------------------------------------------
    USE_ALEMBIC: bool = env_bool("USE_ALEMBIC", True)


    # --------------------------------------------------------------------------
    # Database: echo SQL for debugging (off by default, enable via env)
    # --------------------------------------------------------------------------
    SQLALCHEMY_ECHO: bool = env_bool("SQLALCHEMY_ECHO", False)


    # --------------------------------------------------------------------------
    # Auto-seed roles at startup (configurable via env)
    # --------------------------------------------------------------------------
    AUTO_SEED_ROLES: bool = env_bool("AUTO_SEED_ROLES", True)
