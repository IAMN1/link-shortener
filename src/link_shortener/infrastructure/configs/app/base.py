import os
import secrets
from typing import List, Optional

from sqlalchemy.engine import URL, make_url

from link_shortener.domain.value_objects.short_code import (
    MAX_LENGTH as CODE_MAX_LENGTH,
    MIN_LENGTH as CODE_MIN_LENGTH,
)
from link_shortener.infrastructure.configs.app.env import (
    env_bool, env_float, env_int, env_list, env_str, read_env
)


MAX_BATCH_ITEMS = 100
"""Hard ceiling on how many URLs one request may carry.

The request schema refuses a longer list before anything looks at it, so a
body cannot be turned into unbounded work. ``BATCH_CREATE_LIMIT`` is the
policy inside that ceiling and cannot be set past it: above it, the setting
silently did nothing, because the schema refused the request first and with
its own message.
"""


class BaseConfig:
    """
    Base configuration for the application.

    Contains default settings that can be overridden by environment variables.
    Subclasses should override values for specific environments (development, production, etc.).

    All attributes are documented with their purpose, allowed values, and usage recommendations.
    """

    # ==========================================================================
    # Environment Binding
    # ==========================================================================
    IGNORE_ENV: bool = False
    """
    Whether this configuration class ignores environment variables entirely.
    - False (default): fields declared with env_str/env_int/... read the
        environment on every access.
    - True: every such field returns its declared default, whatever the
        environment says. Used by TestingConfig so that automated tests are
        reproducible on any machine.
    """


    # ==========================================================================
    # Flask Core Settings
    # ==========================================================================
    DEBUG: bool = True
    """
    Enable/disable Flask debug mode.
    - True: auto-reload, detailed error pages, debugger enabled.
    - False: production mode (must be False in staging/production).
    Fixed per profile – it is a deliberate property of the environment, not a
    knob. FLASK_DEBUG affects only the `flask run` CLI, not this value.
    """

    TESTING: bool = False
    """
    Enable/disable Flask testing mode.
    - True: exceptions are propagated, some middleware may be bypassed.
    - False: normal operation.
    Fixed per profile, like DEBUG.
    """


    # ==========================================================================
    # Feature Flags (Global Toggles)
    # ==========================================================================
    LOGGING_ENABLED: bool = env_bool("LOGGING_ENABLED", True)
    """
    Global switch for application logging.
    - true (default): logging is active (LoggerManager will provide actual logger).
    - false: NullLogger is used, all log calls are silently discarded.
    Use false only in special cases (e.g., running one-off scripts where logs are unwanted).
    """

    AUDIT_ENABLED: bool = env_bool("AUDIT_ENABLED", True)
    """
    Global switch for audit logging.
    - true (default): audit events are recorded (URL creation, access, deletion).
    - false: NullAuditLogger is used, no audit trail is kept.
    Should remain true in production for security and compliance.
    """

    CACHE_ENABLED: bool = env_bool("CACHE_ENABLED", True)
    """
    Global switch for caching (both LinkCache and RedirectCache).
    - true (default): actual cache implementation (Redis or InMemory) is used.
    - false: NullCache is used, all cache operations are no-ops.
    Disable only for debugging or in environments without cache infrastructure.
    """

    AUTO_SEED_ROLES: bool = env_bool("AUTO_SEED_ROLES", True)
    """
    Whether to automatically run `seed_base_roles()` at application startup.
    - true (default): ensures minimal set of system roles and permissions exist in DB.
        Idempotent – does not modify existing records. Safe for development.
    - false: no automatic seeding; roles must be created with the CLI command
        `flask db load-base-roles`.
        Recommended for production when strict control over DB changes is required.

    No Alembic revision seeds RBAC. This said "via migrations" and so did
    three other places; the migrations do not, and a deployment that turned
    this off and trusted them came up with an empty `roles` table, where
    anonymous shortening answers 401 because the `guest` role that carries
    `link:create` does not exist.
    """


    # ==========================================================================
    # Logging and Audit Configuration
    # ==========================================================================
    LOGGER_TYPE: str = env_str("LOGGER_TYPE", "auto")
    """
    Type of logger implementation to use.
    - "auto": try structlog, fallback to standard, then null.
    - "structlog": use structured logging (JSON) with structlog.
    - "standard": use Python's standard logging module with custom formatters.
    - "null": discard all logs.
    """

    AUDIT_TYPE: str = env_str("AUDIT_TYPE", "auto")
    """
    Type of audit logger implementation.
    Same values as LOGGER_TYPE.
    """

    LOG_DIR: str = env_str("LOG_DIR", "logs")
    """
    Directory where log files will be written (if LOG_TO_FILE is true).
    Can be absolute or relative path. Created automatically if missing.
    """

    LOG_FILENAME: str = env_str("LOG_FILENAME", "application")
    """
    Base name for general application log file (without extension).
    Final file will be `{LOG_FILENAME}.log`.
    """

    AUDIT_LOG_FILENAME: str = env_str("AUDIT_LOG_FILENAME", "audit")
    """
    Base name for audit log file.
    """

    ERROR_LOG_FILENAME: str = env_str("ERROR_LOG_FILENAME", "error")
    """
    Base name for error-only log file (level >= ERROR).
    """

    LOG_LEVEL: str = env_str("LOG_LEVEL", "DEBUG")
    """
    Minimum log level for application logs.
    Allowed: DEBUG, INFO, WARNING, ERROR, CRITICAL.
    """

    LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"
    """
    Format string for timestamps in log messages.
    """

    LOG_TO_CONSOLE: bool = env_bool("LOG_TO_CONSOLE", True)
    """
    Enable logging to stdout/stderr.
    Recommended for development and containerized environments (Docker).
    """

    LOG_TO_FILE: bool = env_bool("LOG_TO_FILE", False)
    """
    Enable logging to rotating files.
    Recommended for traditional deployments (non-containerized) or when persistent logs are needed.
    """

    ##  Logging levels for third-party libs
    SQLALCHEMY_LOG_LEVEL: str = env_str("SQLALCHEMY_LOG_LEVEL", "WARNING")
    """
    Log level for SQLAlchemy engine logger.
    Set to WARNING or ERROR in production to reduce noise.
    """

    WERKZEUG_LOG_LEVEL: str = env_str("WERKZEUG_LOG_LEVEL", "WARNING")
    """
    Log level for Werkzeug (Flask's development server) logger.
    """

    ## Failover
    FAILOVER_CHECK_INTERVAL: float = env_float("FAILOVER_CHECK_INTERVAL", 30.0)
    """
    Interval in seconds for background health checks in FailoverService.
    Used by LoggerManager and AuditManager to attempt upgrade to primary logger.
    """


    # ==========================================================================
    # Security Settings
    # ==========================================================================
    # Generated once per process, at import. Every worker therefore gets a
    # different pair, which is why using them is warned about rather than
    # merely tolerated -- see ``warn_about_default_secrets``.
    _default_secret_key: str = secrets.token_hex(32)
    _default_pepper: str = secrets.token_hex(32)

    SECRET_KEY: str = env_str("SECRET_KEY", _default_secret_key)
    """
    Flask secret key used for session signing and JWT token generation.
    Must be a strong, random value in production (override via env var).
    Default value is randomly generated at import time – NOT persistent
    across restarts, and not shared between worker processes.
    """

    SHORT_CODE_SECRET_PEPPER: str = env_str("SHORT_CODE_PEPPER", _default_pepper)
    """
    Secret pepper string added to URL before hashing to prevent short code predictability.
    Must be the same across all application instances to ensure identical codes for same URL.
    Override via env var in production.
    """

    SESSION_COOKIE_SECURE: bool = env_bool("SESSION_COOKIE_SECURE", False)
    """
    Secure flag for Flask's own session cookie.
    Declared here so every profile has it – it used to exist only on
    ProductionConfig, which made `config.SESSION_COOKIE_SECURE` raise
    AttributeError everywhere else. ProductionConfig raises the default to true.
    """

    SESSION_COOKIE_SAMESITE: str = env_str("SESSION_COOKIE_SAMESITE", "Lax")
    """
    SameSite policy for Flask's session cookie: Strict, Lax or None.
    """

    SESSION_COOKIE_HTTPONLY: bool = env_bool("SESSION_COOKIE_HTTPONLY", True)
    """
    Forbid JavaScript access to Flask's session cookie. Keep true.
    """

    COOKIE_SECURE: bool = env_bool("COOKIE_SECURE", False)
    """
    Secure flag for authentication cookies set by the auth controller.
    - false (default): cookies are sent over plain HTTP – development only.
    - true: cookies are sent over HTTPS only. Required in production.
    ProductionConfig defaults this to true; it stays overridable via env var.
    """


    # ==========================================================================
    # Application Settings
    # ==========================================================================
    HOST: str = env_str("HOST", "localhost")
    """
    Host address the Flask development server will bind to.
    Use "0.0.0.0" to listen on all interfaces (Docker).
    """

    PORT: int = env_int("PORT", 5000)
    """
    Port number the Flask development server will listen on.
    """

    USE_HTTPS: bool = env_bool("USE_HTTPS", False)
    """
    Whether the service is accessed via HTTPS.
    Affects generation of BASE_URL when DOMAIN is set.
    """

    DOMAIN: Optional[str] = env_str("DOMAIN")
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


    ALLOWED_SCHEMES: List[str] = env_list("ALLOWED_SCHEMES", ["http", "https"])
    """
    List of URL schemes that are permitted for shortening.
    Typically ["http", "https"].
    """

    MAX_URL_LENGTH: int = env_int("MAX_URL_LENGTH", 2048)
    """
    Maximum allowed length of an original URL (RFC 7230 recommends 8000, browsers ~2048).

    Cannot be raised above 2048: that is the width of the ``urls.original_url``
    column, and a URL admitted past it would fail on insert instead.
    """

    ALLOW_INTERNAL_TARGETS: bool = env_bool("ALLOW_INTERNAL_TARGETS", False)
    """
    Whether a shortened URL may point inside the deployment's own network.

    Off by default: a public shortener that admits ``169.254.169.254`` or a
    loopback address forwards requests from the visitor's browser into the
    visitor's network, under this service's domain. Turn it on only for a
    deployment whose whole purpose is shortening intranet links, and which
    is not reachable from outside that intranet.
    """

    SHORT_CODE_LENGTH: int = env_int("SHORT_CODE_LENGTH", 7)
    """
    Desired length of generated short codes.
    Must be between SHORT_CODE_MIN_LENGTH and SHORT_CODE_MAX_LENGTH.
    """

    SHORT_CODE_MIN_LENGTH: int = env_int("SHORT_CODE_MIN_LENGTH", CODE_MIN_LENGTH)
    """
    Shortest code the generator may produce.

    Cannot go below what ``ShortCode`` accepts: the generator would produce
    codes the domain refuses, and every creation would fail on the value
    object rather than on this setting.
    """

    SHORT_CODE_MAX_LENGTH: int = env_int("SHORT_CODE_MAX_LENGTH", CODE_MAX_LENGTH)
    """
    Longest code the generator may produce.

    Cannot go above what ``ShortCode`` accepts, which is also the width of
    the ``urls.short_code`` column.
    """

    ## Code generation
    MAX_COLLISION_ATTEMPTS: int = env_int("MAX_COLLISION_ATTEMPTS", 5)
    """
    Maximum number of attempts to generate a unique short code when collisions occur.
    """

    ## Business rules
    POPULAR_THRESHOLD: int = env_int("POPULAR_THRESHOLD", 100)
    """
    Click count threshold above which a link is considered "popular".
    Used in extended link info responses.
    """

    RECENT_DAYS: int = env_int("RECENT_DAYS", 7)
    """
    Number of days within which a link is considered "recent".
    """

    BATCH_CREATE_LIMIT: int = env_int("BATCH_CREATE_LIMIT", 100)
    """
    Maximum number of URLs allowed in a single batch creation request.
    """

    GUEST_LINK_LIMIT: int = env_int("GUEST_LINK_LIMIT", 10)
    """
    Maximum number of short links a guest (unauthenticated user) can create
    within the window defined by GUEST_LINK_WINDOW_DAYS.
    """

    GUEST_LINK_WINDOW_DAYS: int = env_int("GUEST_LINK_WINDOW_DAYS", 1)
    """
    Time window (in days) during which guest links are counted toward the limit.
    """

    DEFAULT_GUEST_TTL_SECONDS: int = env_int("DEFAULT_GUEST_TTL_SECONDS", 7 * 24 * 3600)
    """
    Time-to-live (in seconds) for guest-created links.

    Both the value applied when no explicit TTL is provided and the longest
    a guest may ask for: as a default alone it was advice, and a guest who
    passed a large ``ttl_seconds`` got a link outliving the limit by
    decades.
    """

    MAX_TTL_SECONDS: int = env_int("MAX_TTL_SECONDS", 10 * 365 * 24 * 3600)
    """
    Longest time-to-live any caller may ask for, ten years by default.

    Unbounded, the number reached ``timedelta`` arithmetic that raises past
    year 9999 -- an ``OverflowError``, which is not a ``ValueError`` and so
    was caught by nothing, turning a request body into a 500.
    """

    # ==========================================================================
    # JWT Authentication Settings
    # ==========================================================================
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = env_int("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", 15)
    """
    Lifetime of access tokens in minutes.
    Short-lived for security (typical: 15-60 minutes).
    """

    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = env_int("JWT_REFRESH_TOKEN_EXPIRE_DAYS", 7)
    """
    Lifetime of refresh tokens in days.
    Longer-lived to allow obtaining new access tokens without re-login.
    """

    JWT_ALGORITHM: str = env_str("JWT_ALGORITHM", "HS256")
    """
    Algorithm used for signing JWT tokens (HS256, RS256, etc.).
    """


    # ==========================================================================
    # Role and Permission Defaults
    # ==========================================================================
    DEFAULT_ROLE_NAME: str = env_str("DEFAULT_ROLE_NAME", "user")
    """
    Name of the role assigned to newly registered users.
    Must exist in the database (created by seed or migrations).
    """

    DEFAULT_ROLE_PERMISSIONS: str = env_str(
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
    DEFAULT_RATE_LIMIT: int = env_int("DEFAULT_RATE_LIMIT", 100)
    """
    Default request limit per window for endpoints without specific configuration.
    """

    DEFAULT_RATE_LIMIT_PERIOD: int = env_int("DEFAULT_RATE_LIMIT_PERIOD", 60)
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
        # Auth endpoints: brute-force protection
        "auth.login": (5, 60),          # 5 attempts per minute per IP
        "auth.register": (3, 3600),     # 3 registrations per hour per IP
        "auth.refresh_token": (10, 60), # 10 refresh attempts per minute
        "auth.logout": (20, 60),        # 20 logout attempts per minute
    }
    """
    Per-endpoint rate limit configurations.
    Key is the Flask endpoint name (as used in url_for).
    Value is a tuple (limit, period_seconds).
    """

    RATE_LIMIT_AUTH_DISABLED: bool = env_bool("RATE_LIMIT_AUTH_DISABLED", False)
    """
    Disable rate limiting for auth endpoints (login, register, refresh, logout).
    Useful during development and testing. Never set to true in production.
    """

    CORS_ORIGINS: list = env_list("CORS_ORIGINS", ["http://localhost:5000"])
    """
    List of allowed CORS origins.
    Set via CORS_ORIGINS env var, comma-separated (e.g. "https://example.com,https://app.example.com").
    """

    TRUSTED_PROXIES: list = env_list("TRUSTED_PROXIES", [])
    """
    List of trusted proxy IP addresses.
    X-Forwarded-For header is only honored when request.remote_addr is in this list.
    Set via TRUSTED_PROXIES env var, comma-separated (e.g. "10.0.0.1,10.0.0.2").
    """


    # ==========================================================================
    # Alembic Integration
    # ==========================================================================
    USE_ALEMBIC: bool = env_bool("USE_ALEMBIC", True)
    """
    Enable Alembic-based schema management.

    - true (default): The application expects the database schema to be managed
      by Alembic migrations. Commands that directly modify the schema
      (`flask db init`, `flask db drop`) are disabled or will show a warning.
      Roles are not seeded by any migration: after `alembic upgrade head`,
      run `flask db load-base-roles` once, or leave AUTO_SEED_ROLES on.

    - false: Schema is managed directly via SQLAlchemy's create_all/drop_all.
      CLI commands `flask db init` and `flask db drop` are allowed, and
      AUTO_SEED_ROLES should typically be True to ensure roles are populated
      at startup.
    """


    # ==========================================================================
    # Database Settings
    # ==========================================================================
    SQLALCHEMY_ECHO: bool = env_bool("SQLALCHEMY_ECHO", False)
    """
    If True, SQLAlchemy logs all SQL statements.
    Should be False in production due to performance and security.
    """

    DATABASE_TYPE: str = env_str("DATABASE_TYPE", "sqlite")
    """
    Database backend: "sqlite" or "postgresql".
    """

    DATABASE_HOST: str = env_str("DATABASE_HOST", "localhost")
    DATABASE_PORT: int = env_int("DATABASE_PORT", 5432)
    DATABASE_NAME: str = env_str("DATABASE_NAME", "db_shortener")
    DATABASE_USER: str = env_str("DATABASE_USER", "")
    DATABASE_PASSWORD: str = env_str("DATABASE_PASSWORD", "")

    DATABASE_URL: str = env_str("DATABASE_URL", "")
    """
    Full database connection URL. If set, overrides individual DATABASE_* settings.
    """

    DATABASE_CONNECT_TIMEOUT: int = env_int("DATABASE_CONNECT_TIMEOUT", 3)
    """
    Seconds to wait for a PostgreSQL connection before giving up.

    Without it the wait is the operating system's TCP timeout, measured in
    minutes: a health check against an unreachable database took 75 seconds
    while the container probe gave up after 10.
    """

    DATABASE_STATEMENT_TIMEOUT: int = env_int("DATABASE_STATEMENT_TIMEOUT", 10)
    """
    Seconds a single SQL statement may run before PostgreSQL aborts it.

    A ceiling per statement, not per request. Without it a locked or slow
    query holds its worker indefinitely; a frozen server is a separate
    problem that this does not solve.
    """

    # Pool parameters (used only for PostgreSQL)
    DATABASE_POOL_PRE_PING: bool = env_bool("DATABASE_POOL_PRE_PING", True)
    """
    Enable connection pool pre-ping to detect stale connections (PostgreSQL only).
    """

    # The pool sizes stay properties because their value depends on
    # DATABASE_TYPE: SQLite does not accept pool arguments at all. They go
    # through _pool_setting() so that a blank value behaves like an unset one,
    # exactly as for every declared env field.
    def _pool_setting(self, name: str, default: int) -> int:
        """
        Read a pool parameter, but only when running on PostgreSQL.

        Args:
            name: Environment variable name.
            default: Value used when the variable is unset or blank.

        Returns:
            The configured value, 0 when the backend is not PostgreSQL, or
            ``default`` when the profile is detached from the environment.

        Raises:
            ValueError: If the value is not a valid integer.
        """
        if self.DATABASE_TYPE != "postgresql":
            return 0

        # IGNORE_ENV has to be honoured here as well, and was not. Reading
        # through read_env() bypasses the EnvField descriptor, which is where
        # the flag is otherwise obeyed -- so `testing`, the one profile that
        # promises detachment, was reading these three from the machine.
        # Not hypothetical: DockerTestConfig sets DATABASE_TYPE to postgresql,
        # so the developer's own DATABASE_POOL_SIZE reached it, and a
        # non-numeric one raised out of get_pool_params() and took the DI
        # container down with it.
        if self.IGNORE_ENV:
            return default

        raw = read_env(name)
        if raw is None:
            return default

        try:
            return int(raw)
        except ValueError as e:
            raise ValueError(
                f"Invalid value for environment variable {name}: {raw!r} ({e})"
            ) from e

    @property
    def DATABASE_POOL_SIZE(self) -> int:
        """Connection pool size (PostgreSQL only)."""
        return self._pool_setting("DATABASE_POOL_SIZE", 20)

    @property
    def DATABASE_MAX_OVERFLOW(self) -> int:
        """Maximum overflow connections beyond pool_size (PostgreSQL only)."""
        return self._pool_setting("DATABASE_MAX_OVERFLOW", 10)

    @property
    def DATABASE_POOL_RECYCLE(self) -> int:
        """Recycle connections after this many seconds (PostgreSQL only)."""
        return self._pool_setting("DATABASE_POOL_RECYCLE", 3600)

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
            return URL.create(
                "sqlite", database=self.DATABASE_NAME
            ).render_as_string(hide_password=False)
        elif self.DATABASE_TYPE == "postgresql":
            # Use psycopg3 driver
            if not all([
                self.DATABASE_USER,
                self.DATABASE_PASSWORD,
                self.DATABASE_HOST,
                self.DATABASE_NAME
            ]):
                raise ValueError("PostgreSQL connection requires DATABASE_USER, DATABASE_PASSWORD, DATABASE_HOST, DATABASE_NAME")
            # Assembled by SQLAlchemy rather than by an f-string, which
            # percent-encodes each part. Interpolated raw, an ordinary "@"
            # in a password split the URL: the host became "ssw0rd@127.0.0.1",
            # so the tail of the password went out in a DNS query and came
            # back in the error message.
            return URL.create(
                "postgresql+psycopg",
                username=self.DATABASE_USER,
                password=self.DATABASE_PASSWORD,
                host=self.DATABASE_HOST,
                port=self.DATABASE_PORT,
                database=self.DATABASE_NAME,
            ).render_as_string(hide_password=False)
        else:
            raise ValueError(f"Unsupported DATABASE_TYPE: {self.DATABASE_TYPE}")

    @property
    def display_database_url(self) -> str:
        """
        Return the database URL with the password masked, for logging.

        Masked by SQLAlchemy's own renderer rather than by a pattern. The
        pattern this replaced matched only up to the last colon, so a
        password containing one -- ``pa:ss:word`` -- was printed all but its
        final segment, into the startup line and the log files.

        Returns:
            URL safe to write to a log.
        """
        try:
            return make_url(self.get_database_url()).render_as_string(
                hide_password=True
            )
        except Exception:
            # Never let a log line be the thing that stops startup. An
            # unparsable URL has no password to reveal in any recognisable
            # place, so nothing is echoed.
            return "<unparsable database url>"

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
    CACHE_LINK_PREFIX: str = env_str("CACHE_LINK_PREFIX", "link_shortener")
    """
    Prefix used for all cache keys (useful for sharing Redis with other apps).
    """

    CACHE_LINK_TTL: int = env_int("CACHE_LINK_TTL", 3600)
    """
    Time-to-live in seconds for cached Link objects.
    Default 1 hour.
    """

    CACHE_STATS_TTL: int = env_int("CACHE_STATS_TTL", 300)
    """
    Time-to-live in seconds for cached service statistics.
    Default 5 minutes.
    """

    # ==========================================================================
    # Redis Cache Settings
    # ==========================================================================
    REDIS_ENABLED: bool = env_bool("REDIS_ENABLED", False)
    """
    Enable Redis as the cache backend.
    If false, InMemoryCache is used (development only).
    """

    REDIS_URL: str = env_str("REDIS_URL", "redis://localhost:6379/0")
    """
    Redis connection URL (format: redis://[:password@]host:port/db).
    """

    ## Redis timeouts
    REDIS_CONNECT_TIMEOUT: int = env_int("REDIS_CONNECT_TIMEOUT", 2)
    """
    Timeout in seconds for establishing Redis connection.
    """

    REDIS_SOCKET_TIMEOUT: int = env_int("REDIS_SOCKET_TIMEOUT", 2)
    """
    Timeout in seconds for Redis socket read/write operations.
    """

    REDIS_RETRY_INTERVAL: int = env_int("REDIS_RETRY_INTERVAL", 10)
    """
    Interval in seconds between reconnection attempts when Redis is down.
    """

    # ==========================================================================
    # Celery Settings
    # ==========================================================================
    CELERY_ENABLED: bool = env_bool("CELERY_ENABLED", False)
    """
    Enable Celery for asynchronous task processing.
    Required for background updates of click statistics and other async jobs.
    """

    CELERY_BROKER_URL: str = env_str("CELERY_BROKER_URL", "")
    """
    Message broker URL for Celery (e.g., Redis URL).
    """

    CELERY_RESULT_BACKEND: str = env_str("CELERY_RESULT_BACKEND", "")
    """
    Result backend URL for Celery (optional, can be same as broker).
    """

    # TODO add monitoring


    # ==========================================================================
    # Health Check Settings
    # ==========================================================================
    HEALTH_CHECK_TIMEOUT: float = env_float("HEALTH_CHECK_TIMEOUT", 5.0)
    """
    Total seconds ``/health`` may spend probing its dependencies.

    A liveness probe that answers late is a probe that did not answer: the
    container healthcheck gives up after 10 seconds and counts the attempt
    as a failure, so a slow dependency would get a working service
    restarted. Components still running when the budget expires are
    reported unavailable.
    """


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
            
            if self.SECRET_KEY == self._default_secret_key:
                errors.append(
                    "SECRET_KEY is using default value – override in .env"
                )

            if self.SHORT_CODE_SECRET_PEPPER == self._default_pepper:
                errors.append(
                    "SHORT_CODE_PEPPER is using default value – override in .env"
                )

        # A database name is a name, not a place to smuggle connection
        # options. "shortener?sslmode=disable" parses back out as a query
        # string, and the connection comes up without TLS while the setting
        # still reads like a plain name -- the one failure here that is
        # silent and that weakens security rather than breaking something.
        # Escaping cannot help: these characters are meaningful in the path
        # of a URL by definition, so the value is refused instead.
        if self.DATABASE_TYPE == "postgresql":
            illegal = [c for c in "?#@/" if c in (self.DATABASE_NAME or "")]
            if illegal:
                errors.append(
                    "DATABASE_NAME must not contain "
                    f"{', '.join(repr(c) for c in illegal)} -- connection "
                    "options belong in their own settings, not in the name"
                )

        for scheme in self.ALLOWED_SCHEMES:
            if scheme not in ["http", "https"]:
                errors.append(f"Invalid URL scheme: {scheme}")

        if self.MAX_URL_LENGTH > 2048:
            errors.append("MAX_URL_LENGTH should not exceed 2048")

        if self.MAX_URL_LENGTH < 1:
            errors.append("MAX_URL_LENGTH must be positive")

        # The generator's bounds have to stay inside what ``ShortCode``
        # accepts and the column stores. Outside them, nothing complains at
        # startup: the generator produces a code, the value object refuses
        # it, and every single creation answers 500.
        if self.SHORT_CODE_MIN_LENGTH < CODE_MIN_LENGTH:
            errors.append(
                f"SHORT_CODE_MIN_LENGTH must be at least {CODE_MIN_LENGTH}"
            )

        if self.SHORT_CODE_MAX_LENGTH > CODE_MAX_LENGTH:
            errors.append(
                f"SHORT_CODE_MAX_LENGTH must not exceed {CODE_MAX_LENGTH}"
            )

        if self.BATCH_CREATE_LIMIT > MAX_BATCH_ITEMS:
            errors.append(
                f"BATCH_CREATE_LIMIT must not exceed {MAX_BATCH_ITEMS} -- "
                "the request schema refuses a longer list first"
            )

        if not (
            self.SHORT_CODE_MIN_LENGTH
            <= self.SHORT_CODE_LENGTH
            <= self.SHORT_CODE_MAX_LENGTH
        ):
            errors.append(
                "SHORT_CODE_LENGTH must lie between SHORT_CODE_MIN_LENGTH "
                "and SHORT_CODE_MAX_LENGTH"
            )

        if self.CACHE_ENABLED and self.REDIS_ENABLED and not self.REDIS_URL:
            errors.append("REDIS_URL must be set when REDIS_ENABLED=True")

        if self.DATABASE_TYPE not in ("sqlite", "postgresql"):
            errors.append(f"Unsupported DATABASE_TYPE: {self.DATABASE_TYPE}")

        errors.extend(self._numeric_errors())

        allowed_levels = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
        if self.LOG_LEVEL.upper() not in allowed_levels:
            errors.append(
                f"Invalid LOG_LEVEL: {self.LOG_LEVEL} "
                f"(allowed: {', '.join(allowed_levels)})"
            )

        if errors:
            raise ValueError("Configuration errors:\n - " + "\n - ".join(errors))


    def default_secrets_in_use(self) -> list:
        """
        Report which secrets are still the per-process random default.

        Worth asking even where ``validate()`` deliberately tolerates it.
        The default is generated once per process, so a deployment running
        more than one worker gives each of them a different value, and
        nothing says so: tokens issued by one worker are rejected by the
        others as invalid, and cache entries written by one are refused by
        the rest. The symptom is intermittent 401s that look like a bug in
        authentication.

        Returns:
            Names of the settings still using a generated default.
        """
        defaults = []
        if self.SECRET_KEY == self._default_secret_key:
            defaults.append("SECRET_KEY")
        if self.SHORT_CODE_SECRET_PEPPER == self._default_pepper:
            defaults.append("SHORT_CODE_PEPPER")
        return defaults

    def _numeric_errors(self) -> List[str]:
        """
        Check numeric settings for values that are syntactically valid but
        meaningless, such as a negative port or a zero-sized batch limit.

        Casting alone does not catch these: ``PORT=-1`` and
        ``GUEST_LINK_LIMIT=-5`` are perfectly good integers, and a float field
        happily accepts ``nan`` or ``inf``. Reporting them here turns a subtle
        misconfiguration into a startup error.

        Returns:
            List of human-readable error messages (empty when all values are sane).
        """
        import math

        errors = []

        if not 1 <= self.PORT <= 65535:
            errors.append(f"PORT must be between 1 and 65535, got {self.PORT}")

        positive_settings = (
            ("GUEST_LINK_LIMIT", self.GUEST_LINK_LIMIT),
            ("GUEST_LINK_WINDOW_DAYS", self.GUEST_LINK_WINDOW_DAYS),
            ("BATCH_CREATE_LIMIT", self.BATCH_CREATE_LIMIT),
            ("MAX_COLLISION_ATTEMPTS", self.MAX_COLLISION_ATTEMPTS),
            ("DEFAULT_RATE_LIMIT", self.DEFAULT_RATE_LIMIT),
            ("DEFAULT_RATE_LIMIT_PERIOD", self.DEFAULT_RATE_LIMIT_PERIOD),
            ("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", self.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
            ("JWT_REFRESH_TOKEN_EXPIRE_DAYS", self.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
        )
        for name, value in positive_settings:
            if value < 1:
                errors.append(f"{name} must be a positive number, got {value}")

        budget = self.HEALTH_CHECK_TIMEOUT
        if not math.isfinite(budget) or budget <= 0:
            errors.append(
                f"HEALTH_CHECK_TIMEOUT must be a positive finite number, "
                f"got {budget}"
            )

        non_negative_settings = (
            ("CACHE_LINK_TTL", self.CACHE_LINK_TTL),
            ("DATABASE_CONNECT_TIMEOUT", self.DATABASE_CONNECT_TIMEOUT),
            ("DATABASE_STATEMENT_TIMEOUT", self.DATABASE_STATEMENT_TIMEOUT),
            ("CACHE_STATS_TTL", self.CACHE_STATS_TTL),
            ("POPULAR_THRESHOLD", self.POPULAR_THRESHOLD),
            ("RECENT_DAYS", self.RECENT_DAYS),
        )
        for name, value in non_negative_settings:
            if value < 0:
                errors.append(f"{name} must not be negative, got {value}")

        # Both of these are lifetimes, and a lifetime of zero seconds does
        # not mean "immediately" anywhere in this service -- it means
        # "forever". Zero here is therefore not a strict setting but the
        # removal of the limit: DEFAULT_GUEST_TTL_SECONDS=0 gave every guest
        # a link that never expires, quietly, through the ``min()`` that
        # applies the guest ceiling.
        for name, value in (
            ("DEFAULT_GUEST_TTL_SECONDS", self.DEFAULT_GUEST_TTL_SECONDS),
            ("MAX_TTL_SECONDS", self.MAX_TTL_SECONDS),
        ):
            if value < 1:
                errors.append(
                    f"{name} must be a positive number of seconds "
                    f"(0 would mean 'never expires'), got {value}"
                )

        interval = self.FAILOVER_CHECK_INTERVAL
        if not math.isfinite(interval) or interval <= 0:
            errors.append(
                f"FAILOVER_CHECK_INTERVAL must be a positive finite number, "
                f"got {interval}"
            )

        return errors
