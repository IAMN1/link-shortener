import os

from link_shortener.infrastructure.config.base import BaseConfig


class ProductionConfig(BaseConfig):
    """Configuration for production environment."""

    DEBUG: bool = False
    TESTING: bool = False

    # ========== logging settings ==========
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
    LOG_TO_CONSOLE: bool = os.environ.get("LOG_TO_CONSOLE", "false").lower() == "true"
    LOG_TO_FILE: bool = os.environ.get("LOG_TO_FILE", "true").lower() == "true"
    # LOG_DIR: str = '/var/log/link_shortener'  # Стандартный путь для логов в Linux

    # ========== Security App ==========
    @property
    def SECRET_KEY(self) -> str:
        """Secret key must be set in environment."""

        key = os.environ.get("SECRET_KEY")
        if not key:
            raise ValueError("SECRET_KEY must be set in environment")

        return key

    @property
    def SHORT_CODE_SECRET_PEPPER(self) -> str:
        """Pepper must be set in environment."""

        pepper = os.environ.get("SHORT_CODE_PEPPER")
        if not pepper:
            raise ValueError(
                "SHORT_CODE_PEPPER must be set in environment"
            )

        return pepper

    # ========== App settings ==========
    HOST: str = os.environ.get("HOST", "0.0.0.0")
    PORT: int = int(os.environ.get("PORT", 8000))

    @property
    def BASE_URL(self) -> str:
        """Base URL for production – uses DOMAIN environment variable if set."""

        domain = os.environ.get("DOMAIN")
        if domain:
            use_https = os.environ.get("USE_HTTPS", "true").lower() == "true"
            scheme = "https" if use_https else "http"
            return f"{scheme}://{domain}"
        return f"http://{self.HOST}:{self.PORT}/"

    # ========== Limits ==========
    MAX_REQUESTS_PER_MINUTE: int = int(os.environ.get("MAX_REQUESTS_PER_MINUTE", 50))
    BATCH_CREATE_LIMIT: int = int(os.environ.get("BATCH_CREATE_LIMIT", 100))

    # ========== Database settings ==========
    @property
    def DATABASE_URL(self) -> str:
        """Database URL must be set in environment."""

        url = os.environ.get("DATABASE_URL")
        if not url:
            raise ValueError("DATABASE_URL must be set in environment")

        return url

    @property
    def DATABASE_POOL_SIZE(self) -> int:
        return int(os.environ.get("DATABASE_POOL_SIZE", 50))

    @property
    def DATABASE_MAX_OVERFLOW(self) -> int:
        return int(os.environ.get("DATABASE_MAX_OVERFLOW", 20))

    # ========== Redis cache settings ==========
    REDIS_ENABLED: bool = os.environ.get("REDIS_ENABLED", "true").lower() == "true"

    @property
    def REDIS_URL(self) -> str:
        """Redis URL must be set in environment if Redis is enabled."""

        url = os.environ.get("REDIS_URL")
        if not url:
            raise ValueError("REDIS_URL must be set in environment")
        return url
    
    def validate(self) -> None:
        """Enforce presence of required environment variables."""
        super().validate()
        # Принудительный вызов свойств, 
        # чтобы убедиться, что переменные окружения заданы
        _ = self.SECRET_KEY
        _ = self.SHORT_CODE_SECRET_PEPPER
        _ = self.DATABASE_URL
        
        if self.REDIS_ENABLED:
            _ = self.REDIS_URL

        if not os.environ.get("DOMAIN"):
            raise ValueError("DOMAIN environment variable must be set in production")
