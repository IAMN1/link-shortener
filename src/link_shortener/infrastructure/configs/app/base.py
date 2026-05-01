import os
import secrets
from typing import List, Optional


class BaseConfig:
    """
    Base configuration for the application.

    Contains default settings that can be overridden by environment variables.
    Subclasses should override values for specific environments (development, production, etc.).

    All attributes are documented with their purpose, allowed values, and usage recommendations.
    """

    # ==========================================================================
    # Flask Core Settings
    # ==========================================================================
    DEBUG: bool = True
    """
    Enable/disable Flask debug mode.
    - True: auto-reload, detailed error pages, debugger enabled.
    - False: production mode (must be False in staging/production).
    Set via FLASK_DEBUG environment variable or subclass override.
    """

    TESTING: bool = False
    """
    Enable/disable Flask testing mode.
    - True: exceptions are propagated, some middleware may be bypassed.
    - False: normal operation.
    Set via FLASK_TESTING or subclass override.
    """


    # ==========================================================================
    # Feature Flags (Global Toggles)
    # ==========================================================================
    LOGGING_ENABLED: bool = os.environ.get("LOGGING_ENABLED", "true").lower() == "true"
    """
    Global switch for application logging.
    - true (default): logging is active (LoggerManager will provide actual logger).
    - false: NullLogger is used, all log calls are silently discarded.
    Use false only in special cases (e.g., running one-off scripts where logs are unwanted).
    """

    AUDIT_ENABLED: bool = os.environ.get("AUDIT_ENABLED", "true").lower() == "true"
    """
    Global switch for audit logging.
    - true (default): audit events are recorded (URL creation, access, deletion).
    - false: NullAuditLogger is used, no audit trail is kept.
    Should remain true in production for security and compliance.
    """

    CACHE_ENABLED: bool = os.environ.get("CACHE_ENABLED", "true").lower() == "true"
    """
    Global switch for caching (both LinkCache and RedirectCache).
    - true (default): actual cache implementation (Redis or InMemory) is used.
    - false: NullCache is used, all cache operations are no-ops.
    Disable only for debugging or in environments without cache infrastructure.
    """

    AUTO_SEED_ROLES: bool = os.environ.get("AUTO_SEED_ROLES", "true").lower() == "true"
    """
    Whether to automatically run `seed_base_roles()` at application startup.
    - true (default): ensures minimal set of system roles and permissions exist in DB.
        Idempotent – does not modify existing records. Safe for development.
    - false: no automatic seeding; roles must be created via migrations or CLI commands.
        Recommended for production when strict control over DB changes is required.
    """


    # ==========================================================================
    # Logging and Audit Configuration
    # ==========================================================================
    LOGGER_TYPE: str = os.environ.get("LOGGER_TYPE", "auto")
    """
    Type of logger implementation to use.
    - "auto": try structlog, fallback to standard, then null.
    - "structlog": use structured logging (JSON) with structlog.
    - "standard": use Python's standard logging module with custom formatters.
    - "null": discard all logs.
    """

    AUDIT_TYPE: str = os.environ.get("AUDIT_TYPE", "auto")
    """
    Type of audit logger implementation.
    Same values as LOGGER_TYPE.
    """

    LOG_DIR: str = os.environ.get("LOG_DIR", "logs")
    """
    Directory where log files will be written (if LOG_TO_FILE is true).
    Can be absolute or relative path. Created automatically if missing.
    """

    LOG_FILENAME: str = os.environ.get("LOG_FILENAME", "application")
    """
    Base name for general application log file (without extension).
    Final file will be `{LOG_FILENAME}.log`.
    """

    AUDIT_LOG_FILENAME: str = os.environ.get("AUDIT_LOG_FILENAME", "audit")
    """
    Base name for audit log file.
    """

    ERROR_LOG_FILENAME: str = os.environ.get("ERROR_LOG_FILENAME", "error")
    """
    Base name for error-only log file (level >= ERROR).
    """

    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "DEBUG")
    """
    Minimum log level for application logs.
    Allowed: DEBUG, INFO, WARNING, ERROR, CRITICAL.
    """

    LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"
    """
    Format string for timestamps in log messages.
    """

    LOG_TO_CONSOLE: bool = os.environ.get("LOG_TO_CONSOLE", "true").lower() == "true"
    """
    Enable logging to stdout/stderr.
    Recommended for development and containerized environments (Docker).
    """

    LOG_TO_FILE: bool = os.environ.get("LOG_TO_FILE", "false").lower() == "true"
    """
    Enable logging to rotating files.
    Recommended for traditional deployments (non-containerized) or when persistent logs are needed.
    """

    ##  Logging levels for third-party libs
    SQLALCHEMY_LOG_LEVEL: str = os.environ.get("SQLALCHEMY_LOG_LEVEL", "WARNING")
    """
    Log level for SQLAlchemy engine logger.
    Set to WARNING or ERROR in production to reduce noise.
    """

    WERKZEUG_LOG_LEVEL: str = os.environ.get("WERKZEUG_LOG_LEVEL", "WARNING")
    """
    Log level for Werkzeug (Flask's development server) logger.
    """

    ## Failover
    FAILOVER_CHECK_INTERVAL: float = float(os.environ.get("FAILOVER_CHECK_INTERVAL", 30.0))
    """
    Interval in seconds for background health checks in FailoverService.
    Used by LoggerManager and AuditManager to attempt upgrade to primary logger.
    """


    # ==========================================================================
    # Security Settings
    # ==========================================================================
    _DEFAULT_SECRET_KEY: str = secrets.token_hex(32)
    _DEFAULT_PEPPER: str = secrets.token_hex(32)

    SECRET_KEY: str = os.environ.get("SECRET_KEY", _DEFAULT_SECRET_KEY)
    """
    Flask secret key used for session signing and JWT token generation.
    Must be a strong, random value in production (override via env var).
    Default value is randomly generated at import time – NOT persistent across restarts!
    """

    SHORT_CODE_SECRET_PEPPER: str = os.environ.get("SHORT_CODE_PEPPER", _DEFAULT_PEPPER)
    """
    Secret pepper string added to URL before hashing to prevent short code predictability.
    Must be the same across all application instances to ensure identical codes for same URL.
    Override via env var in production.
    """


    # ==========================================================================
    # Application Settings
    # ==========================================================================
    HOST: str = os.environ.get("HOST", "localhost")
    """
    Host address the Flask development server will bind to.
    Use "0.0.0.0" to listen on all interfaces (Docker).
    """

    PORT: int = int(os.environ.get("PORT", 5000))
    """
    Port number the Flask development server will listen on.
    """

    USE_HTTPS: bool = os.environ.get("USE_HTTPS", "false").lower() == "true"
    """
    Whether the service is accessed via HTTPS.
    Affects generation of BASE_URL when DOMAIN is set.
    """

    DOMAIN: Optional[str] = os.environ.get("DOMAIN")
    """
    Public domain name of the service (e.g., "short.example.com").
    If set, BASE_URL uses this domain and scheme from USE_HTTPS.
    If not set, BASE_URL is constructed from HOST and PORT.
    """

    @property
    def BASE_URL(self) -> str:
        """
        Base URL of the service used for constructing full short URLs.
        """
        if self.DOMAIN:
            scheme = "https" if self.USE_HTTPS else "http"
            return f"{scheme}://{self.DOMAIN}"
        return f"http://{self.HOST}:{self.PORT}/"


    ALLOWED_SCHEMES: List[str] = os.environ.get("ALLOWED_SCHEMES", "http,https").split(",")
    """
    List of URL schemes that are permitted for shortening.
    Typically ["http", "https"].
    """

    MAX_URL_LENGTH: int = 2048
    """
    Maximum allowed length of an original URL (RFC 7230 recommends 8000, browsers ~2048).
    """

    SHORT_CODE_LENGTH: int = 7
    """
    Desired length of generated short codes.
    Must be between SHORT_CODE_MIN_LENGTH and SHORT_CODE_MAX_LENGTH.
    """

    SHORT_CODE_MIN_LENGTH: int = 6
    SHORT_CODE_MAX_LENGTH: int = 10

    ## Code generation
    MAX_COLLISION_ATTEMPTS: int = int(os.environ.get("MAX_COLLISION_ATTEMPTS", 5))
    """
    Maximum number of attempts to generate a unique short code when collisions occur.
    """

    ## Business rules
    POPULAR_THRESHOLD: int = int(os.environ.get("POPULAR_THRESHOLD", 100))
    """
    Click count threshold above which a link is considered "popular".
    Used in extended link info responses.
    """

    RECENT_DAYS: int = int(os.environ.get("RECENT_DAYS", 7))
    """
    Number of days within which a link is considered "recent".
    """

    BATCH_CREATE_LIMIT: int = int(os.environ.get("BATCH_CREATE_LIMIT", 100))
    """
    Maximum number of URLs allowed in a single batch creation request.
    """


    # ==========================================================================
    # JWT Authentication Settings
    # ==========================================================================
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.environ.get("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 15))
    """
    Lifetime of access tokens in minutes.
    Short-lived for security (typical: 15-60 minutes).
    """

    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.environ.get("JWT_REFRESH_TOKEN_EXPIRE_DAYS", 7))
    """
    Lifetime of refresh tokens in days.
    Longer-lived to allow obtaining new access tokens without re-login.
    """

    JWT_ALGORITHM: str = os.environ.get("JWT_ALGORITHM", "HS256")
    """
    Algorithm used for signing JWT tokens (HS256, RS256, etc.).
    """


    # ==========================================================================
    # Role and Permission Defaults
    # ==========================================================================
    DEFAULT_ROLE_NAME: str = os.environ.get("DEFAULT_ROLE_NAME", "user")
    """
    Name of the role assigned to newly registered users.
    Must exist in the database (created by seed or migrations).
    """

    DEFAULT_ROLE_PERMISSIONS: str = os.environ.get(
        "DEFAULT_ROLE_PERMISSIONS", 
        "link:create,link:view_own,link:delete_own,stats:view_basic"
    )
    """
    Comma-separated list of permission names for the default role.
    Used only if the default role needs to be created programmatically.
    """


    @property
    def DEFAULT_ROLE_PERMISSIONS_SET(self) -> set:
        return set(p.strip() for p in self.DEFAULT_ROLE_PERMISSIONS.split(',') if p.strip())


    # ==========================================================================
    # Rate Limiting
    # ==========================================================================
    DEFAULT_RATE_LIMIT: int = int(os.environ.get("DEFAULT_RATE_LIMIT", 100))
    """
    Default request limit per window for endpoints without specific configuration.
    """

    DEFAULT_RATE_LIMIT_PERIOD: int = int(os.environ.get("DEFAULT_RATE_LIMIT_PERIOD", 60))
    """
    Default time window in seconds for rate limiting.
    """

    RATE_LIMITS: dict = {
        # Endpoint-specific overrides: (limit, period_seconds)
        "api.create_short_link": (30, 60),
        "api.get_link_info": (100, 60),
        "api.get_extended_link_info": (50, 60),
        "api.batch_create": (5, 60),
        "api.get_stats": (10, 60),
        "redirect_to_original": (200, 60),
        "health": (10, 5),
    }
    """
    Per-endpoint rate limit configurations.
    Key is the Flask endpoint name (as used in url_for).
    Value is a tuple (limit, period_seconds).
    """


    # ==========================================================================
    # Alembic Integration
    # ==========================================================================
    USE_ALEMBIC: bool = os.environ.get("USE_ALEMBIC", "true").lower() == "true"
    """
    Enable Alembic-based schema management.

    - true (default): The application expects the database schema to be managed
      by Alembic migrations. Commands that directly modify the schema
      (`flask db init`, `flask db drop`) are disabled or will show a warning.
      It is recommended to set AUTO_SEED_ROLES=False because roles are seeded
      within the Alembic migration that creates the RBAC tables.

    - false: Schema is managed directly via SQLAlchemy's create_all/drop_all.
      CLI commands `flask db init` and `flask db drop` are allowed, and
      AUTO_SEED_ROLES should typically be True to ensure roles are populated
      at startup.
    """


    # ==========================================================================
    # Database Settings
    # ==========================================================================
    SQLALCHEMY_ECHO: bool = os.environ.get("SQLALCHEMY_ECHO", "true").lower() == "true"
    """
    If True, SQLAlchemy logs all SQL statements.
    Should be False in production due to performance and security.
    """

    DATABASE_TYPE: str = os.environ.get("DATABASE_TYPE","sqlite") # "sqlite" or "postgressql"
    """
    Database backend: "sqlite" or "postgresql".
    """

    DATABASE_HOST: str = os.environ.get("DATABASE_HOST", "localhost")
    DATABASE_PORT: int = int(os.environ.get("DATABASE_PORT", 5432))
    DATABASE_NAME: str = os.environ.get("DATABASE_NAME", "db_shortener")
    DATABASE_USER: str = os.environ.get("DATABASE_USER", "")
    DATABASE_PASSWORD: str = os.environ.get("DATABASE_PASSWORD", "")
    
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "")
    """
    Full database connection URL. If set, overrides individual DATABASE_* settings.
    """

    # Pool parameters (used only for PostgreSQL)
    DATABASE_POOL_PRE_PING: bool = os.environ.get("DATABASE_POOL_PRE_PING", "true").lower() == "true"
    """
    Enable connection pool pre-ping to detect stale connections (PostgreSQL only).
    """

    @property
    def DATABASE_POOL_SIZE(self) -> int:
        """Connection pool size (PostgreSQL only)."""
        if self.DATABASE_TYPE == "postgresql":
            return int(os.environ.get("DATABASE_POOL_SIZE", 20))
        return 0

    @property
    def DATABASE_MAX_OVERFLOW(self) -> int:
        """Maximum overflow connections beyond pool_size (PostgreSQL only)."""
        if self.DATABASE_TYPE == "postgresql":
            return int(os.environ.get("DATABASE_MAX_OVERFLOW", 10))
        return 0

    @property
    def DATABASE_POOL_RECYCLE(self) -> int:
        """Recycle connections after this many seconds (PostgreSQL only)."""
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
            if not all([
                self.DATABASE_USER,
                self.DATABASE_PASSWORD,
                self.DATABASE_HOST,
                self.DATABASE_NAME
            ]):
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


    # ==========================================================================
    # Cache Settings
    # ==========================================================================
    CACHE_LINK_PREFIX: str = os.environ.get("CACHE_LINK_PREFIX", "link_shortener")
    """
    Prefix used for all cache keys (useful for sharing Redis with other apps).
    """

    CACHE_LINK_TTL: int = int(os.environ.get("CACHE_LINK_TTL", 3600))
    """
    Time-to-live in seconds for cached Link objects.
    Default 1 hour.
    """

    CACHE_STATS_TTL: int = int(os.environ.get("CACHE_STATS_TTL", 300))
    """
    Time-to-live in seconds for cached service statistics.
    Default 5 minutes.
    """

    # ==========================================================================
    # Redis Cache Settings
    # ==========================================================================
    REDIS_ENABLED: bool = os.environ.get("REDIS_ENABLED", "false").lower() == "true"
    """
    Enable Redis as the cache backend.
    If false, InMemoryCache is used (development only).
    """

    REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    """
    Redis connection URL (format: redis://[:password@]host:port/db).
    """

    ## Redis timeouts
    REDIS_CONNECT_TIMEOUT: int = int(os.environ.get("REDIS_CONNECT_TIMEOUT", 2))
    """
    Timeout in seconds for establishing Redis connection.
    """

    REDIS_SOCKET_TIMEOUT: int = int(os.environ.get("REDIS_SOCKET_TIMEOUT", 2))
    """
    Timeout in seconds for Redis socket read/write operations.
    """

    REDIS_RETRY_INTERVAL: int = int(os.environ.get("REDIS_RETRY_INTERVAL", 10))
    """
    Interval in seconds between reconnection attempts when Redis is down.
    """

    # ==========================================================================
    # Celery Settings
    # ==========================================================================
    CELERY_ENABLED: bool = os.environ.get("CELERY_ENABLED", "false").lower() == "true"
    """
    Enable Celery for asynchronous task processing.
    Required for background updates of click statistics and other async jobs.
    """

    CELERY_BROKER_URL: str = os.environ.get("CELERY_BROKER_URL", "")
    """
    Message broker URL for Celery (e.g., Redis URL).
    """

    CELERY_RESULT_BACKEND: str = os.environ.get("CELERY_RESULT_BACKEND", "")
    """
    Result backend URL for Celery (optional, can be same as broker).
    """

    # TODO add monitoring


    # ==========================================================================
    # Validation Configuration
    # ==========================================================================
    def validate(self) -> None:
        """
        Validate critical settings.

        In non-debug/non-test modes, checks that SECRET_KEY and PEPPER are not
        using the default values. Also validates allowed schemes, URL length,
        Redis URL, and database type.

        Raises:
            ValueError: If any validation fails.
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

        if self.DATABASE_TYPE not in ("sqlite", "postgresql"):
            errors.append(f"Unsupported DATABASE_TYPE: {self.DATABASE_TYPE}")

        if errors:
            raise ValueError("Configuration errors:\n - " + "\n - ".join(errors))
