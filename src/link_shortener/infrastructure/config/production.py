import logging
import os

from link_shortener.infrastructure.config.base import BaseConfig


class ProductionConfig(BaseConfig):
    DEBUG: bool = False
    TESTING: bool = False

    # ========== logging settings ==========
    LOG_LEVEL: int = logging.INFO
    LOG_TO_CONSOLE: bool = False
    LOG_TO_FILE: bool = True
    # LOG_DIR: str = '/var/log/link_shortener'  # Стандартный путь для логов в Linux

    # ========== Security App ==========
    @property
    def SECRET_KEY(self) -> str:
        key = os.environ.get("SECRET_KEY")
        if not key:
            raise ValueError("SECRET_KEY должен быть установлен в переменных окружения")

        return key

    @property
    def SHORT_CODE_SECRET_PEPPER(self) -> str:
        pepper = os.environ.get("SHORT_CODE_PEPPER")
        if not pepper:
            raise ValueError(
                "SHORT_CODE_PEPPER должен быть установлен в переменных окружения"
            )

        return pepper

    # ========== App settings ==========
    HOST: str = os.environ.get("HOST", "0.0.0.0")
    PORT: int = int(os.environ.get("PORT", 8000))

    @property
    def BASE_URL(self) -> str:
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
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise ValueError(
                "DATABASE_URL должен быть установлен в переменных среды коружения"
            )

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
        url = os.environ.get("REDIS_URL")
        if not url:
            raise ValueError("REDIS_URL должен быть установлен в переменных окружения")
        return url
