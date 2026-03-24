import os

from link_shortener.infrastructure.config.base import BaseConfig


class DevelopmentConfig(BaseConfig):
    """Configuration for development environment."""

    DEBUG: bool = True
    TESTING: bool = False


    # ========== Cache settings ==========
    CACHE_LINK_TTL: int = int(os.environ.get("CACHE_LINK_TTL", 20))
    CACHE_STATS_TTL: int = int(os.environ.get("CACHE_STATS_TTL", 20))

    # ========== Redis cache settings ==========
    REDIS_ENABLED: bool = os.environ.get("REDIS_ENABLED", "false").lower() == "true"
    REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
