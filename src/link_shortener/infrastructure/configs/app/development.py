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


    # --------------------------------------------------------------------------
    # Mail: aimed at the local catcher, which speaks no TLS
    # --------------------------------------------------------------------------
    MAIL_HOST: str = env_str("MAIL_HOST", "localhost")
    MAIL_PORT: int = env_int("MAIL_PORT", 1025)
    MAIL_USE_TLS: bool = env_bool("MAIL_USE_TLS", False)
    MAIL_FROM: str = env_str("MAIL_FROM", "no-reply@link-shortener.local")
    """
    Defaults for the Mailpit container in ``docker-compose.override.yml``:
    SMTP on 1025, no TLS, no authentication, and every message kept in its
    own web interface on 8025 instead of being delivered.

    TLS is off here and nowhere else. The catcher does not offer it, and
    the traffic never leaves the machine. ``MAIL_USERNAME`` stays empty, so
    no password is at stake -- and if a developer sets one, the base
    validation refuses the combination rather than sending it in the clear.
    """
