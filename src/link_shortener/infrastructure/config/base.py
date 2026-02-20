import logging
import os
import secrets
from typing import List, Optional
from urllib.parse import urlparse


class BaseConfig:
    DEBUG: bool = True
    TESTING: bool = False

    # ========== Feature flags ==========
    LOGGING_ENABLED: bool = True
    AUDIT_ENABLED: bool = True
    CACHE_ENABLED: bool = True

    # ========== logging settings ==========
    LOG_DIR: str = os.environ.get("LOG_DIR", "logs")
    # имя будет дополненно датой
    LOG_FILENAME: str = "link_shortener"
    LOG_LEVEL: int = logging.INFO
    LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"
    LOG_MAX_BYTES: int = 10 * 1024 * 1024  # 10 MB
    LOG_BACKUP_FILES_COUNT: int = 5
    LOG_TO_CONSOLE: bool = True
    LOG_TO_FILE: bool = True

    # ========== Security App ==========
    _DEFAULT_SECRET_KEY: str = secrets.token_hex(32)
    _DEFAULT_PEPPER: str = secrets.token_hex(32)

    SECRET_KEY: str = os.environ.get("SECRET_KEY", _DEFAULT_SECRET_KEY)
    SHORT_CODE_SECRET_PEPPER: str = os.environ.get("SHORT_CODE_PEPPER", _DEFAULT_PEPPER)

    # ========== App settings ==========
    HOST: str = os.environ.get("HOST", "localhost")
    PORT: int = int(os.environ.get("PORT", 5000))

    @property
    def BASE_URL(self) -> str:
        """Базовый URL (динамическое вычисление)"""
        return f"http://{self.HOST}:{self.PORT}/"

    ALLOWED_SCHEMES: List[str] = ["http", "https"]
    MAX_URL_LENGTH: int = 2048
    SHORT_CODE_LENGTH: int = 7
    SHORT_CODE_MIN_LENGTH: int = 6
    SHORT_CODE_MAX_LENGTH: int = 10

    # ========== Limits ==========
    MAX_REQUESTS_PER_MINUTE: int = 100
    BATCH_CREATE_LIMIT: int = 100  # Макс URL за один пакетный запрос

    # ========== Database settings ==========
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///dev.db")

    @property
    def DATABASE_POOL_SIZE(self) -> int:
        if self.DATABASE_URL.startswith("postgresql://"):
            return int(os.environ.get("DATABASE_POOL_SIZE", 20))
        return 0

    @property
    def DATABASE_MAX_OVERFLOW(self) -> int:
        if self.DATABASE_URL.startswith("postgresql://"):
            return int(os.environ.get("DATABASE_MAX_OVERFLOW", 10))
        return 0

    @property
    def DATABASE_POOL_RECYCLE(self) -> int:
        if self.DATABASE_URL.startswith("postgresql://"):
            return int(os.environ.get("DATABASE_POOL_RECYCLE", 3600))
        return 0

    # ========== Cache settings ==========
    CACHE_LINK_PREFIX: str = os.environ.get("CACHE_LINK_PREFIX", "link_shortener")
    CACHE_LINK_TTL: int = int(os.environ.get("CACHE_LINK_TTL", 3600))
    CACHE_STATS_TTL: int = int(os.environ.get("CACHE_STATS_TTL", 300))

    # ========== Redis cache settings ==========
    REDIS_ENABLED: bool = os.environ.get("REDIS_ENABLED", "false").lower() == "true"
    REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    @property
    def REDIS_HOST(self) -> Optional[str]:
        try:
            parsed = urlparse(self.REDIS_URL)
            return parsed.hostname
        except Exception:
            return None

    @property
    def REDIS_PORT(self) -> Optional[int]:
        try:
            parsed = urlparse(self.REDIS_URL)
            return parsed.port or 6379
        except Exception:
            return None

    @property
    def REDIS_DB(self) -> Optional[int]:
        try:
            parsed = urlparse(self.REDIS_URL)
            path = parsed.path.strip("/")
            return int(path) if path.isdigit() else 0
        except Exception:
            return None

    # TODO add monitoring

    # ========== Validation Configuration ==========
    def validate(self) -> None:
        """Проверка конфигурации на корректность"""
        errors = []

        # Пропуск проверки секретов в режиме разработки/тестирования
        if not self.DEBUG and not self.TESTING:
            
            if self.SECRET_KEY == self._DEFAULT_SECRET_KEY:
                errors.append(
                    "SECRET_KEY используется значение по умолчанию — замените его в .env"
                )

            if self.SHORT_CODE_SECRET_PEPPER == self._DEFAULT_PEPPER:
                errors.append(
                    "SHORT_CODE_PEPPER используется значение по умолчанию — замените его в .env"
                )

        for scheme in self.ALLOWED_SCHEMES:
            if scheme not in ["http", "https"]:
                errors.append(f"Недопустимая схема URL: {scheme}")

        if self.MAX_URL_LENGTH > 2048:
            errors.append("MAX_URL_LENGTH не должен превышать 2048 символов")

        if self.REDIS_ENABLED and not self.REDIS_URL.startswith("redis://"):
            errors.append('REDIS_URL должен начинаться с "redis://"')

        if errors:
            raise ValueError("Ошибки в конфигурации:\n - " + "\n - ".join(errors))
