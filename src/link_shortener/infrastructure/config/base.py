import os
import secrets
from typing import List, Optional


class BaseConfig:
    """
    Base configuration for the application.

    Contains default settings that can be overridden by environment variables.
    Subclasses should override values for specific environments (development, production, etc.).
    """
    DEBUG: bool = True
    TESTING: bool = False

    # =============== Feature flags ==================================================
    LOGGING_ENABLED: bool = os.environ.get("LOGGING_ENABLED", "true").lower() == "true"
    AUDIT_ENABLED: bool = os.environ.get("AUDIT_ENABLED", "true").lower() == "true"
    CACHE_ENABLED: bool = os.environ.get("CACHE_ENABLED", "true").lower() == "true"

    # =============== Logging and Audit settings ===============================================
    LOGGER_TYPE: str = os.environ.get("LOGGER_TYPE", "auto") # auto / structlog / standard / null
    AUDIT_TYPE: str = os.environ.get("AUDIT_TYPE", "auto") # auto / structlog / standard / null
    LOG_DIR: str = os.environ.get("LOG_DIR", "logs")
    LOG_FILENAME: str = os.environ.get("LOG_FILENAME", "application")
    AUDIT_LOG_FILENAME: str = os.environ.get("AUDIT_LOG_FILENAME", "audit")
    ERROR_LOG_FILENAME: str = os.environ.get("ERROR_LOG_FILENAME", "error")
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "DEBUG")
    LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"
    LOG_TO_CONSOLE: bool = os.environ.get("LOG_TO_CONSOLE", "true").lower() == "true"
    LOG_TO_FILE: bool = os.environ.get("LOG_TO_FILE", "false").lower() == "true"

    ##  Logging levels for third-party libs
    SQLALCHEMY_LOG_LEVEL: str = os.environ.get("SQLALCHEMY_LOG_LEVEL", "WARNING")
    WERKZEUG_LOG_LEVEL: str = os.environ.get("WERKZEUG_LOG_LEVEL", "WARNING")

    ## Failover
    FAILOVER_CHECK_INTERVAL: float = float(os.environ.get("FAILOVER_CHECK_INTERVAL", 30.0))

    # =============== Security App ===================================================
    _DEFAULT_SECRET_KEY: str = secrets.token_hex(32)
    _DEFAULT_PEPPER: str = secrets.token_hex(32)

    SECRET_KEY: str = os.environ.get("SECRET_KEY", _DEFAULT_SECRET_KEY)
    SHORT_CODE_SECRET_PEPPER: str = os.environ.get("SHORT_CODE_PEPPER", _DEFAULT_PEPPER)

    # =============== App settings ===================================================
    HOST: str = os.environ.get("HOST", "localhost")
    PORT: int = int(os.environ.get("PORT", 5000))
    USE_HTTPS: bool = os.environ.get("USE_HTTPS", "false").lower() == "true"
    DOMAIN: Optional[str] = os.environ.get("DOMAIN")

    ## Code generation
    MAX_COLLISION_ATTEMPTS: int = int(os.environ.get("MAX_COLLISION_ATTEMPTS", 5))

    ## Business rules
    POPULAR_THRESHOLD: int = int(os.environ.get("POPULAR_THRESHOLD", 100))
    RECENT_DAYS: int = int(os.environ.get("RECENT_DAYS", 7))


    @property
    def BASE_URL(self) -> str:
        """Base URL of the service (used for constructing short URLs)."""
        return f"http://{self.HOST}:{self.PORT}/"

    ALLOWED_SCHEMES: List[str] = os.environ.get("ALLOWED_SCHEMES", "http,https").split(",")
    MAX_URL_LENGTH: int = 2048
    SHORT_CODE_LENGTH: int = 7
    SHORT_CODE_MIN_LENGTH: int = 6
    SHORT_CODE_MAX_LENGTH: int = 10

    # =============== Limits =========================================================
    MAX_REQUESTS_PER_MINUTE: int = int(os.environ.get("MAX_REQUESTS_PER_MINUTE", 100))
    BATCH_CREATE_LIMIT: int = int(os.environ.get("BATCH_CREATE_LIMIT", 100))

    # =============== Database settings ==============================================
    SQLALCHEMY_ECHO: bool = os.environ.get("SQLALCHEMY_ECHO", "true").lower() == "true"

    DATABASE_TYPE: str = os.environ.get("DATABASE_TYPE","sqlite") # "sqlite" or "postgressql"
    DATABASE_HOST: str = os.environ.get("DATABASE_HOST", "localhost")
    DATABASE_PORT: int = int(os.environ.get("DATABASE_PORT", 5432))
    DATABASE_NAME: str = os.environ.get("DATABASE_NAME", "db_shortener")
    DATABASE_USER: str = os.environ.get("DATABASE_USER", "")
    DATABASE_PASSWORD: str = os.environ.get("DATABASE_PASSWORD", "")
    
    # If DATABASE_URL is set directly, it will be used instead of constructing from parts
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "")
    
    # Pool parameters (used only for PostgreSQL)
    DATABASE_POOL_PRE_PING: bool = os.environ.get("DATABASE_POOL_PRE_PING", "true").lower() == "true"

    @property
    def DATABASE_POOL_SIZE(self) -> int:
        """Database connection pool size (for PostgreSQL)."""
        if self.DATABASE_TYPE == "postgresql":
            return int(os.environ.get("DATABASE_POOL_SIZE", 20))
        return 0

    @property
    def DATABASE_MAX_OVERFLOW(self) -> int:
        """Maximum overflow connections for pool (PostgreSQL)."""
        if self.DATABASE_TYPE == "postgresql":
            return int(os.environ.get("DATABASE_MAX_OVERFLOW", 10))
        return 0

    @property
    def DATABASE_POOL_RECYCLE(self) -> int:
        """Recycle connections after this many seconds (PostgreSQL)."""
        if self.DATABASE_TYPE == "postgresql":
            return int(os.environ.get("DATABASE_POOL_RECYCLE", 3600))
        return 0

    def get_database_url(self) -> str:
        """
        Construct database URL from individual parameters or return explicitly set URL.

        Returns:
            SQLAlchemy-compatible database URL.

        Raises:
            ValueError: If DATABASE_TYPE is unsupported or required parameters are missing.
        """
        if self.DATABASE_URL:
            return self.DATABASE_URL
        
        if self.DATABASE_TYPE == "sqlite":
            # SQLite: DATABASE_NAME is the file path
            return f"sqlite:///{self.DATABASE_NAME}"
        elif self.DATABASE_TYPE == "postgresql":
            # Use psycopg3 driver
            if (not self.DATABASE_USER or not self.DATABASE_PASSWORD 
                or not self.DATABASE_HOST or not self.DATABASE_NAME):
                raise ValueError("PostgreSQL connection requires DATABASE_USER, DATABASE_PASSWORD, DATABASE_HOST, DATABASE_NAME")
            return f"postgresql+psycopg://{self.DATABASE_USER}:{self.DATABASE_PASSWORD}@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"
        else:
            raise ValueError(f"Unsupported DATABASE_TYPE: {self.DATABASE_TYPE}")

    @property
    def display_database_url(self) -> str:
        """Return database URL with password masked for logging."""
        url = self.get_database_url()
        import re
        # Маскируем пароль: заменяем часть между :// и @
        return re.sub(r':[^:]+@', ':***@', url)

    def get_pool_params(self) -> dict:
        """
        Return a dictionary of connection pool parameters suitable for SQLAlchemy.

        Returns:
            Dictionary with keys: pool_size, max_overflow, pool_recycle, pool_pre_ping.
        """
        return {
            "pool_size": self.DATABASE_POOL_SIZE,
            "max_overflow": self.DATABASE_MAX_OVERFLOW,
            "pool_recycle": self.DATABASE_POOL_RECYCLE,
            "pool_pre_ping": self.DATABASE_POOL_PRE_PING,
        }


    # =============== Cache settings =================================================
    CACHE_LINK_PREFIX: str = os.environ.get("CACHE_LINK_PREFIX", "link_shortener")
    CACHE_LINK_TTL: int = int(os.environ.get("CACHE_LINK_TTL", 3600))
    CACHE_STATS_TTL: int = int(os.environ.get("CACHE_STATS_TTL", 300))

    # =============== Redis cache settings ===========================================
    REDIS_ENABLED: bool = os.environ.get("REDIS_ENABLED", "false").lower() == "true"
    REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    ## Redis timeouts
    REDIS_CONNECT_TIMEOUT: int = int(os.environ.get("REDIS_CONNECT_TIMEOUT", 2))
    REDIS_SOCKET_TIMEOUT: int = int(os.environ.get("REDIS_SOCKET_TIMEOUT", 2))
    REDIS_RETRY_INTERVAL: int = int(os.environ.get("REDIS_RETRY_INTERVAL", 10))

    # TODO add monitoring

    # =============== Validation Configuration =======================================
    def validate(self) -> None:
        """
        Validate configuration settings.

        Raises:
            ValueError: If any setting is invalid.
        """
        
        errors = []

        # In non-debug/non-test modes, ensure secrets are not default
        if not self.DEBUG and not self.TESTING:
            
            if self.SECRET_KEY == self._DEFAULT_SECRET_KEY:
                errors.append(
                    "SECRET_KEY is using default value – override in .env"
                )

            if self.SHORT_CODE_SECRET_PEPPER == self._DEFAULT_PEPPER:
                errors.append(
                    "SHORT_CODE_PEPPER is using default value – override in .env"
                )

        for scheme in self.ALLOWED_SCHEMES:
            if scheme not in ["http", "https"]:
                errors.append(f"Invalid URL scheme: {scheme}")

        if self.MAX_URL_LENGTH > 2048:
            errors.append("MAX_URL_LENGTH should not exceed 2048")

        if self.CACHE_ENABLED and self.REDIS_ENABLED and not self.REDIS_URL:
            errors.append("REDIS_URL must be set when REDIS_ENABLED=True")

        if errors:
            raise ValueError("Configuration errors:\n - " + "\n - ".join(errors))
