import re
import secrets
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

from sqlalchemy.engine import URL, make_url

from link_shortener.application.dtos.batch import MAX_BATCH_ITEMS
from link_shortener.domain.value_objects.email import EMAIL_PATTERN_RE
from link_shortener.domain.value_objects.short_code import (
    MAX_LENGTH as CODE_MAX_LENGTH,
    MIN_LENGTH as CODE_MIN_LENGTH,
)
from link_shortener.infrastructure.configs.app.env import (
    env_bool, env_float, env_int, env_list, env_str, read_env, read_env_for
)


JOURNAL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
"""What a journal may be called.

A name, not a path: the three journal settings are joined to ``LOG_DIR``
and given a ``.log`` suffix by ``os.path.join``, which is perfectly willing
to leave the directory if the name asks it to. Anchored at both ends and
starting on a letter or a digit, so ``..`` and ``./`` are refused along
with every separator -- a leading dot is refused too, since a journal
nobody can see is not a journal anybody reads.
"""


def _find_project_root() -> Optional[Path]:
    """
    Locate the source tree this module was loaded from, if it is one.

    Searched for by marker rather than counted in levels up from this
    file: the image installs the package into ``site-packages``, so the
    module that runs in production is nowhere near the project.

    Both markers are required -- ``pyproject.toml`` alone appears inside
    installed third-party packages, and a stray one above an installed
    copy would silently become the anchor.

    Returns:
        The directory holding ``pyproject.toml`` and ``src``, or None when
        this module runs from an installed copy rather than a source tree.
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file() and (parent / "src").is_dir():
            return parent

    return None


DATABASE_DIRECTORY = Path("datas") / "databases"
"""Where a SQLite file lives, relative to the project root.

One place to look, and not the root: a database file beside the compose
files and the README reads as part of the project rather than as something
a run left behind. Only relative names are anchored here -- an absolute
``DATABASE_NAME`` and an explicit ``DATABASE_URL`` are the caller saying
where they want it.
"""

PROJECT_ROOT = _find_project_root()
"""Directory the project is laid out from, or None outside a source tree.

None is not a failure: it means nothing here knows better than the caller
where a relative path should point, so the path is left as it was -- which
is what every release before this one did everywhere.
"""


MASK = "***"
"""What a masked secret is rendered as, in the userinfo and in the query alike."""


def display_url(url: str) -> str:
    """
    Render a database URL with its password masked.

    Masked by SQLAlchemy's own renderer rather than by a pattern. The
    pattern this replaced matched only up to the last colon, so a password
    containing one -- ``pa:ss:word`` -- was printed all but its final
    segment, into the startup line and the log files.

    Args:
        url: URL to render.

    Returns:
        URL safe to write to a log or a terminal.
    """
    try:
        parsed = make_url(url)
        if not parsed.password:
            # SQLAlchemy renders ``:***`` for a password that is the empty
            # string, which reads as "a password is set" in a startup log.
            # Since a PostgreSQL URL may legitimately carry none -- peer,
            # trust, .pgpass, PGPASSWORD -- the difference is worth
            # keeping: an operator debugging authentication reads this
            # line to find out what was sent.
            #
            # ``_replace`` and not ``set``: the latter reads ``None`` as
            # "leave this alone", so it returned the empty password
            # unchanged and the mask stayed.
            parsed = parsed._replace(password=None)

        # The renderer masks one place a password can be: the userinfo
        # component it parsed into ``password``. libpq takes it in a
        # second, and psycopg is handed it just as readily --
        # ``...?password=s3cret`` reaches the driver as ``password=``,
        # measured through ``create_connect_args``. Rendered by
        # ``hide_password`` alone that spelling came out verbatim, into
        # the startup line and from there into ``application.log``, which
        # is read under ``logs:view`` -- a permission `auditor` holds, and
        # a journal this project's own rule says holds no secrets.
        #
        # Masked by key rather than refused at validation, because this
        # function is the one place that promises the result is safe to
        # print, and it is called on URLs from several sources.
        credentials = {
            name: value for name, value in parsed.query.items()
            if name.lower().endswith("password")
        }
        if not credentials:
            return parsed.render_as_string(hide_password=True)

        parsed = parsed.set(
            query={**parsed.query, **dict.fromkeys(credentials, MASK)}
        )
        rendered = parsed.render_as_string(hide_password=True)

        # The renderer percent-encodes query values, so the mask arrives
        # as ``%2A%2A%2A`` and the same line ends up masked two different
        # ways -- ``:***@`` in the userinfo and that in the query. Put
        # back here rather than by choosing an alphanumeric mask, because
        # the two places should read alike and ``***`` is what every other
        # line in this project prints.
        return rendered.replace(quote(MASK, safe=""), MASK)
    except Exception:
        # Never let a log line be the thing that stops a command. An
        # unparsable URL has no password to reveal in any recognisable
        # place, so nothing is echoed.
        return "<unparsable database url>"


DEFAULT_POSTGRESQL_DRIVER = "psycopg"
"""Driver a PostgreSQL URL gets when it does not name one.

SQLAlchemy's default for a bare ``postgresql://`` is psycopg2, which this
project does not install -- ``pyproject.toml`` asks for ``psycopg[binary]``,
which is psycopg 3 and a different module. So a URL without a driver raised
``ModuleNotFoundError: No module named 'psycopg2'`` at the first connection.
The URL assembled from the ``DATABASE_*`` parts has always said
``postgresql+psycopg``; this is the same answer for the URL an operator
writes out in full.
"""


def normalise_backend(url: str) -> str:
    """
    Rewrite the ``postgres://`` spelling of a PostgreSQL URL as ``postgresql://``.

    The same database, written the way half the industry hands it out:
    Heroku, Render, Railway and Supabase all print ``postgres://``.
    SQLAlchemy dropped that alias in 1.4 and refuses it, so a value copied
    from a hosting dashboard would die at the first connection.

    A driver written into the scheme is kept, so ``postgres+psycopg2://``
    becomes ``postgresql+psycopg2://`` rather than losing the driver the
    operator asked for. A URL that names none gets
    ``DEFAULT_POSTGRESQL_DRIVER``, since SQLAlchemy's own default is
    psycopg2 and this project installs psycopg 3.

    Args:
        url: URL as configured.

    Returns:
        The URL with its scheme normalised; the value unchanged when it is
        not a PostgreSQL one, and when it does not parse -- an unusable
        string is left for the engine to refuse with its own message.
    """
    try:
        parsed = make_url(url)
    except Exception:
        return url

    # Lower-cased first: a URL scheme is case-insensitive by RFC 3986, so
    # ``POSTGRES://`` -- what a copied-out-of-a-document value can look
    # like -- would otherwise survive unchanged and then be refused with
    # "put a PostgreSQL URL there", the dead end this function removes.
    driver = parsed.drivername.lower()
    if driver in ("postgres", "postgresql"):
        return parsed.set(
            drivername=f"postgresql+{DEFAULT_POSTGRESQL_DRIVER}"
        ).render_as_string(hide_password=False)

    if driver.startswith("postgres+"):
        return parsed.set(
            drivername="postgresql" + driver[len("postgres"):]
        ).render_as_string(hide_password=False)

    return url


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
    - "auto": structlog first, standard behind it. Not null behind
        those two: the chain is exactly the two, so a call both refuse
        is refused outright rather than quietly swallowed.
    - "structlog": use structured logging (JSON) with structlog.
    - "standard": use Python's standard logging module with custom formatters.
    - "null": discard all logs.
    """

    AUDIT_TYPE: str = env_str("AUDIT_TYPE", "auto")
    """
    Type of audit logger implementation.
    Same values as LOGGER_TYPE.
    """

    _default_log_dir: str = "datas/logs"
    """Where logs go when nothing says otherwise, before anchoring.

    Beside the databases, under ``datas``: what a run leaves behind
    belongs in one place, and that place is not the project root.
    """

    @property
    def LOG_DIR(self) -> str:
        """
        Directory where log files will be written (if LOG_TO_FILE is true).

        A relative value is anchored to the project root, for the reason
        given in ``_sqlite_path``: read against the working directory
        instead, the same setting names a different directory for every
        process, and a worker started elsewhere writes its logs where
        nobody looks for them. An absolute value is handed back as it
        stands, and so is any value outside a source tree, where there is
        no root to anchor to. Created automatically if missing.

        Returns:
            The directory to write logs into.
        """
        configured = read_env_for(self, "LOG_DIR", self._default_log_dir)
        if PROJECT_ROOT is None:
            return configured

        return str(PROJECT_ROOT / configured)

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

    Declared on the base so every profile carries it; ``ProductionConfig``
    raises the default to true.
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

    HSTS_MAX_AGE: int = env_int("HSTS_MAX_AGE", 31536000)
    """
    Seconds a browser should remember to reach this service over TLS only.

    Read only where ``USE_HTTPS`` is on, so a development run on plain HTTP
    never sends the header whatever this says. A year is the value the
    header is worth sending at all: the point of it is the *first* request
    of a later visit, which is the one a network can still redirect, and a
    short window closes that only for people who came back this week.

    ``0`` switches it off, which is the setting for a deployment whose
    reverse proxy sends the header itself -- two ``Strict-Transport-Security``
    headers are not additive, and the browser reads the first.

    Deliberately without ``includeSubDomains`` and without ``preload``.
    Both reach past this service: the first speaks for every sibling on the
    domain, several of which may not have TLS at all, and the second is
    recorded in the browsers themselves and takes months to undo. A
    deployment that wants either has a proxy in front of it and can say so
    there, where the person setting it owns the whole domain.
    """

    DOMAIN: Optional[str] = env_str("DOMAIN")
    """
    Public domain name of the service (e.g., "short.example.com").
    If set, BASE_URL uses this domain and scheme from USE_HTTPS.
    If not set, BASE_URL is constructed from HOST and PORT.
    """

    @property
    def domain_value(self) -> str:
        """
        ``DOMAIN`` as everything that uses it should see it.

        Stripped, like the database URL and the alembic handoff are
        stripped and for the same reason: a value read out of a file or a
        Kubernetes Secret arrives with a trailing newline, and left alone
        that newline goes into ``BASE_URL`` and into every short link
        built from it. The check and the builder read this one value, so
        neither can be validating a string the other does not use.

        Returns:
            The configured domain without surrounding whitespace, or an
            empty string when it is unset.
        """
        return (self.DOMAIN or "").strip()

    @property
    def BASE_URL(self) -> str:
        """
        Base URL of the service used for constructing full short URLs.

        Every profile is served by this one. ``production`` carried a copy
        of it, word for word, which decided nothing: the three names it
        reads are resolved on the instance, so the profile's own ``HOST``,
        ``PORT`` and ``USE_HTTPS`` reach this body anyway. What a second
        copy could do was drift from the first.

        Returns:
            The address short links are written against.
        """
        # ``domain_value`` rather than ``DOMAIN``: stripped, so a value
        # arriving from a Secret with a trailing newline does not put one
        # inside every short link, and so this agrees with the check that
        # a deployed profile names a domain at all.
        domain = self.domain_value
        if domain:
            scheme = "https" if self.USE_HTTPS else "http"
            return f"{scheme}://{domain}"
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

    ## Visit statistics
    VISIT_TRACKING_ENABLED: bool = env_bool("VISIT_TRACKING_ENABLED", True)
    """
    Whether an opened link is recorded as an event, not only counted.

    Off, ``urls.clicks`` still counts and every chart with time on an axis
    stays empty -- that is what the service did before the table existed.
    On, one row is written per redirect, by the same background task that
    moves the counter.
    """

    VISIT_RETENTION_DAYS: int = env_int("VISIT_RETENTION_DAYS", 90)
    """
    How long a raw visit row is kept before the sweep deletes it.

    Days that have ended are folded into one row per link per day first,
    so the daily chart keeps its shape after the rows behind them are
    gone. It is the one that does: a folded day is a total and a robot
    count, and the bucketed span above it carries breakdowns by device,
    by browser and by link that no fold keeps -- so that chart reaches
    back exactly this far and no further.

    Which is why this number and the longest span on offer are both
    ninety days. Shorten it and the ninety-day view shrinks with it while
    the daily chart below it does not, and nothing on the page says why
    the two disagree.

    Zero disables the sweep, and the table then grows without limit --
    which is a choice, not an accident, and has to be made deliberately.
    """

    SECURITY_EVENT_RETENTION_DAYS: int = env_int(
        "SECURITY_EVENT_RETENTION_DAYS", 365
    )
    """
    How long a raw security event row is kept before the sweep deletes it.

    A year rather than the ninety days the visits get, and the difference
    is what the two tables are for. A visit is traffic: last quarter's
    redirects answer a question about popularity that this quarter's
    answer better. A sign-in is evidence, and the question asked of it --
    "when did this account last get in, and from where" -- is usually
    asked long after the fact.

    They also fill at different rates. At ten redirects a second the visit
    table takes a million rows a day; the security events are sign-ins,
    account changes and journal reads, which a busy deployment counts in
    thousands.

    Days that have ended are folded into one row per kind per day first,
    so the long-range chart keeps its shape after the rows behind it are
    gone. Zero disables the sweep, and the table then grows without limit
    -- which is a choice, not an accident.
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
    # Interface Language
    # ==========================================================================
    SUPPORTED_LANGUAGES: List[str] = env_list("SUPPORTED_LANGUAGES", ["en", "ru", "zh"])
    """
    Languages the interface is offered in, best first.

    Order is not decoration: it is the order ``Accept-Language`` is matched
    against, so a caller who accepts several of them with equal weight gets
    the first one named here.

    A language listed without a catalogue on disk is not an error -- gettext
    falls back to the untranslated text, which is English. The opposite is
    the real fault, and it is what the deployment check looks for: a
    catalogue nobody can reach because its language is not named here.
    """

    DEFAULT_LANGUAGE: str = env_str("DEFAULT_LANGUAGE", "en")
    """
    Language for a caller who asked for none.

    Which is most callers of the API and, measured, every request the test
    suite and the browser run make: neither sends ``Accept-Language`` at
    all. So this is not an edge case -- it is the language a program sees.
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
        # Auth endpoints: brute-force protection
        "auth.login": (5, 60),          # 5 attempts per minute per IP
        "auth.register": (3, 3600),     # 3 registrations per hour per IP
        "auth.refresh_token": (10, 60), # 10 refresh attempts per minute
        "auth.logout": (20, 60),        # 20 logout attempts per minute
        # Confirmation links. The first is the only thing standing between
        # a stranger and unlimited guesses at a token, which OWASP asks for
        # by name -- "Implement appropriate protection to prevent users
        # from brute-forcing tokens in the URL, such as rate limiting".
        # A 256-bit token is not going to be guessed either way; the limit
        # is what stops the attempt from costing the service anything.
        "auth.verify_email": (10, 60),
        # The second sends mail to whatever address is named, so without a
        # limit it is a way to have this service deliver mail to strangers
        # -- and a way to bury a real user's inbox under confirmations
        # they did not ask for.
        "auth.resend_verification": (3, 3600),
        # Changing a password takes the current one, so this route answers
        # whether a guess at it was right -- to a caller who is already
        # signed in, and therefore only useful to somebody working from a
        # session they took rather than an account they own. Five a minute
        # is the sign-in limit, for the same reason the sign-in has one.
        "auth.change_password": (5, 60),
        # Mail on demand to whatever address is named, so the same limit
        # as `resend_verification` and for the same two reasons: without
        # it this is a way to have the service deliver mail to strangers,
        # and a way to bury a real user's inbox under reset links they did
        # not ask for.
        "auth.forgot_password": (3, 3600),
        # The only thing between a stranger and unlimited guesses at a
        # reset token, which OWASP asks for by name. A 256-bit token will
        # not be guessed either way; the limit is what stops the attempt
        # from costing the service anything.
        "auth.reset_password": (10, 60),
    }
    """
    Per-endpoint rate limit configurations.
    Key is the Flask endpoint name (as used in url_for).
    Value is a tuple (limit, period_seconds).

    Every key must name a route the throttle can actually reach, and every
    value must be a pair of positive integers. A name nothing answers to,
    an exempt endpoint, a route served from the static prefix and a
    malformed value are all refused at startup rather than ignored: such
    an entry reads like a live limit and throttles nothing.

    ``RATE_LIMIT_AUTH_DISABLED`` is the one exception, and a deliberate
    one: it switches every ``auth.*`` limit off at run time and is not
    refused here.
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

    DATABASE_DIR: str = env_str("DATABASE_DIR", str(DATABASE_DIRECTORY))
    """
    Directory a SQLite file is put in. Ignored by PostgreSQL.

    Relative to the project root, so the default puts the file in
    ``datas/databases`` however the process was started. An absolute value
    is taken as it stands and works outside a source tree as well -- which
    is the case a container is: the package is installed into
    site-packages, there is no project directory above it, and a
    deployment that wants ``/var/lib/shortener`` says so here.

    An absolute ``DATABASE_NAME`` and an explicit ``DATABASE_URL`` both
    win over this: they already say where the file goes.
    """

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
        # The backend actually being opened, for the reason spelled out in
        # ``database_backend``: ``DATABASE_TYPE`` describes how a URL is
        # assembled from parts and is not read at all once ``DATABASE_URL``
        # is set, so asking it would answer ``sqlite`` for a deployment
        # whose URL names PostgreSQL and drop all three pool settings.
        if self.database_backend() != "postgresql":
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
        """
        Connection pool size (PostgreSQL only).

        Per process, not per deployment. The image serves with sync
        gunicorn workers, so a process holds one request and one
        connection at a time; the pool is a ceiling on what that process
        may keep open, and the measurement in
        ``docs/development.md`` found the ceiling never approached --
        1, 2, 5 and 20 gave the same throughput and the same number of
        server-side connections.

        Five rather than twenty because the ceiling is multiplied by the
        worker count: twenty plus five of overflow across four workers is
        100 connections, which is a PostgreSQL's own default limit
        exactly, leaving none for the migration, the worker or a psql
        session.
        """
        return self._pool_setting("DATABASE_POOL_SIZE", 5)

    @property
    def DATABASE_MAX_OVERFLOW(self) -> int:
        """Maximum overflow connections beyond pool_size (PostgreSQL only)."""
        return self._pool_setting("DATABASE_MAX_OVERFLOW", 5)

    @property
    def DATABASE_POOL_RECYCLE(self) -> int:
        """Recycle connections after this many seconds (PostgreSQL only)."""
        return self._pool_setting("DATABASE_POOL_RECYCLE", 3600)

    def _sqlite_path(self) -> str:
        """
        Anchor a relative SQLite file to the project's database directory.

        SQLAlchemy leaves a relative path to Python, which reads it against
        the working directory of the process -- "the actual filename to be
        used starts with the characters to the right of the third slash"
        and nothing more is said about where that filename is looked for.
        The result was a database whose identity depended on where the
        process was started: running from ``src/`` created a second, empty
        ``src/db_shortener.db`` and reported no error at all, because an
        absent SQLite file is created rather than refused.

        The anchor is ``DATABASE_DIR`` -- ``datas/databases`` unless a
        deployment says otherwise -- rather than the root itself, so that
        there is one place to look for a database file and it is not the
        same place as the source, the compose files and the docs. A name
        with directories in it keeps them, underneath that directory.

        The directory is created here, and this is the one method that
        knows the path: SQLite creates a missing *file* and refuses a
        missing *directory* with "unable to open database file", and the
        callers that would meet that -- the application, the CLI, alembic
        in its own subprocess -- have nothing else in common.

        ``:memory:`` is handed back untouched -- it is not a file. An
        absolute ``DATABASE_NAME`` is returned as it stands: it already
        says where the file goes. An explicit ``DATABASE_URL`` never
        reaches here -- ``get_database_url`` returns it first -- so a
        caller who writes the URL by hand keeps whatever they wrote.

        Outside a source tree a *relative* ``DATABASE_DIR`` has no root to
        anchor to, and the name is returned as given: an installed copy
        has no project directory, and inventing one would put the database
        somewhere no deployment asked for. An absolute ``DATABASE_DIR``
        needs no root and is honoured there too, which is how a container
        names a mounted volume.

        Returns:
            The path to hand to SQLAlchemy.
        """
        name = self.DATABASE_NAME
        if name == ":memory:" or Path(name).is_absolute():
            return name

        directory = Path(self.DATABASE_DIR)
        if not directory.is_absolute():
            if PROJECT_ROOT is None:
                return name
            directory = PROJECT_ROOT / directory

        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)

    def get_database_url(self) -> str:
        """
        Construct database URL from individual parameters or return explicitly set URL.

        Returns:
            SQLAlchemy-compatible database URL.

        Raises:
            ValueError: If DATABASE_TYPE is unsupported or required parameters are missing.
        """
        if self.DATABASE_URL:
            # Stripped, and the migration path strips its own handoff the
            # same way. Left alone, a value with a trailing newline -- what
            # a URL read out of a file or a k8s Secret arrives as -- named a
            # *different* database on each side: the application
            # opened "app.db\n" while `flask alembic upgrade` migrated
            # "app.db", so the service came up on an empty file beside the
            # one that had just been migrated.
            #
            # Normalised here rather than where the URL is checked, because
            # every reader has to see the same string: the check would
            # otherwise pass a value that create_engine then refuses.
            return normalise_backend(self.DATABASE_URL.strip())

        if self.DATABASE_TYPE == "sqlite":
            # SQLite: DATABASE_NAME is the file path
            return URL.create(
                "sqlite", database=self._sqlite_path()
            ).render_as_string(hide_password=False)
        elif self.DATABASE_TYPE == "postgresql":
            # Use psycopg3 driver
            #
            # DATABASE_PASSWORD is deliberately not in this list. A password
            # is one of several ways PostgreSQL authenticates and the only
            # one this setting can carry: `peer` and `trust` need none at
            # all, and `.pgpass` and `PGPASSWORD` hand libpq one that never
            # passes through here. Demanding it refused a working
            # deployment, and refused it inconsistently -- the same
            # connection written as DATABASE_URL was accepted, because that
            # path reads no part.
            missing = [
                name
                for name, value in (
                    ("DATABASE_USER", self.DATABASE_USER),
                    ("DATABASE_HOST", self.DATABASE_HOST),
                    ("DATABASE_NAME", self.DATABASE_NAME),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    "PostgreSQL connection requires "
                    f"{', '.join(missing)}"
                )
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

        Returns:
            URL safe to write to a log.
        """
        try:
            return display_url(self.get_database_url())
        except Exception:
            # A URL that cannot even be assembled is reported the same way
            # as one that cannot be parsed: a log line must never be the
            # thing that stops startup.
            return "<unparsable database url>"

    def database_backend(self) -> str:
        """
        Return the backend the configuration will actually connect to.

        Read off the URL that will be opened rather than off
        ``DATABASE_TYPE``, which says how a URL is *assembled* from parts
        and is not read at all once ``DATABASE_URL`` is set. The two would
        otherwise disagree, and the engine -- its pool, its timeouts, its
        connection pragmas -- is built from this answer.

        Returns:
            SQLAlchemy backend name -- ``postgresql``, ``sqlite``, ... --
            falling back to ``DATABASE_TYPE`` when no URL can be built.
        """
        try:
            return make_url(self.get_database_url()).get_backend_name()
        except Exception:
            return self.DATABASE_TYPE

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
    # Mail Settings
    # ==========================================================================
    MAIL_ENABLED: bool = env_bool("MAIL_ENABLED", False)
    """
    Enable the outgoing mail channel.

    Off by default, and that default is a decision rather than caution: a
    deployment that has not been told where to submit mail must not try,
    because the attempt is a socket timeout on the request path. With this
    off the service still registers accounts -- what it cannot do is send
    them anything, which ``NullMailer`` records once per message.
    """

    MAIL_HOST: str = env_str("MAIL_HOST", "")
    """
    Hostname of the submission server.

    No default, and the empty one is load-bearing. With ``"localhost"``
    here the validation below could never fire: a blank environment
    variable reads as unset, so the check would see the default and pass,
    and a deployment that enabled mail without saying where would submit
    to whatever answers on its own loopback -- or, far more often, to
    nothing, one socket timeout per registration. ``DevelopmentConfig``
    sets its own default, because there the local catcher is the point.
    """

    MAIL_PORT: int = env_int("MAIL_PORT", 587)
    """
    Submission port.

    587 is the STARTTLS submission port and pairs with ``MAIL_USE_TLS``;
    465 is Implicit TLS and pairs with ``MAIL_USE_SSL``. RFC 8314 asks for
    both to be supported and considers them equivalent when TLS is
    actually required at both ends, so this is a deployment's choice and
    not a security one -- the security is in the flag beside it.
    """

    MAIL_USERNAME: str = env_str("MAIL_USERNAME", "")
    """
    Account to authenticate to the submission server as.

    Empty means no authentication, which is what a relay listening on the
    loopback interface expects. Set, it obliges the connection to be
    encrypted: the mailer refuses to send the password otherwise.
    """

    MAIL_PASSWORD: str = env_str("MAIL_PASSWORD", "")
    """
    Password for ``MAIL_USERNAME``.
    """

    MAIL_USE_TLS: bool = env_bool("MAIL_USE_TLS", True)
    """
    Negotiate STARTTLS after connecting.

    On by default: a submission that begins in the clear carries the
    password and the confirmation link where anyone on the path can read
    them, and a default that has to be switched on is a default nobody
    switches on.
    """

    MAIL_USE_SSL: bool = env_bool("MAIL_USE_SSL", False)
    """
    Connect with TLS already established, without a STARTTLS step.

    Mutually exclusive with ``MAIL_USE_TLS``: STARTTLS inside a connection
    that is already encrypted is not a stronger arrangement, it is a
    protocol error, and the server answers it as one.
    """

    MAIL_FROM: str = env_str("MAIL_FROM", "")
    """
    Address the service sends from.

    Has to be an address the submission server will accept as a sender;
    receiving domains check that against SPF and DMARC, and a mismatch is
    delivered to nobody rather than refused loudly.
    """

    REQUIRE_MAIL_TLS: bool = False
    """
    Whether this profile refuses to submit mail without TLS.

    A class attribute rather than a setting, and read from no environment
    variable, because it is the profile's own standard: development aims
    at a catcher on the loopback interface that speaks no TLS, and the
    deployed profiles have no such excuse. RFC 8314 section 3.3 treats
    STARTTLS on 587 and Implicit TLS on 465 as equivalent, but only "if
    both the client and the server are configured to require successful
    negotiation of TLS prior to Message Submission" -- this is the client
    half of that requirement.
    """

    MAIL_TIMEOUT: float = env_float("MAIL_TIMEOUT", 10.0)
    """
    Seconds any single blocking socket operation with the server may take.

    Not optional and not merely tuning. Left unset, ``smtplib`` falls back
    to the global default socket timeout, which is ``None``: a server that
    accepts the connection and then says nothing holds the caller for as
    long as it likes.
    """


    # ==========================================================================
    # Email Confirmation Settings
    # ==========================================================================
    EMAIL_VERIFICATION_TTL_HOURS: int = env_int("EMAIL_VERIFICATION_TTL_HOURS", 24)
    """
    Hours a confirmation link stays usable.

    OWASP asks that such a token "expire after an appropriate period", and
    appropriate is a trade rather than a number: shorter is less time for
    a link sitting in a mailbox to be worth stealing, longer is fewer
    people who open their mail the next morning and find a dead link.
    """

    PASSWORD_RESET_TTL_MINUTES: int = env_int("PASSWORD_RESET_TTL_MINUTES", 60)
    """
    Minutes a password reset link stays usable.

    Minutes rather than hours, and a shorter default than the confirmation
    above, because the two tokens are not worth the same. A confirmation
    proves somebody can read a mailbox; a reset link is a working way into
    the account, and it sits in that mailbox for its whole lifetime. OWASP's
    Forgot Password Cheat Sheet asks for "a short expiration time" and names
    20 minutes to an hour as the usual range.

    The floor is what the trade is made against: a link too short-lived is
    one that dies while its owner is still walking to their computer, and
    every one of those is a second request and a second live token.
    """

    UNVERIFIED_ACCOUNT_TTL_HOURS: int = env_int("UNVERIFIED_ACCOUNT_TTL_HOURS", 72)
    """
    Hours an account may stay unconfirmed before ``flask maintenance
    clean-unverified`` deletes it. Nothing deletes it on its own -- that
    command has to be scheduled, exactly like ``clean-expired``.

    Without the sweep an unconfirmed registration holds its address forever:
    registering it again is refused because the account exists, and nobody
    can sign in to it. Anyone could reserve addresses they do not own, in
    bulk, and the real owners would find themselves locked out of
    registering at all.

    Must not be shorter than ``EMAIL_VERIFICATION_TTL_HOURS`` -- an account
    swept away while its own link is still valid turns a working
    confirmation into a dead one.
    """


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

        Raises:
            ValueError: If any validation fails.
        """
        errors = self._collect_errors()

        # Deduplicated, order kept: one fault can reach the list by two
        # roads, and the same sentence twice reads as two problems.
        unique = list(dict.fromkeys(errors))
        if unique:
            raise ValueError("Configuration errors:\n - " + "\n - ".join(unique))


    def _collect_errors(self) -> List[str]:
        """
        Gather everything wrong with this configuration, rather than the first thing.

        Split out of ``validate`` so that a profile adding demands of its
        own extends one list instead of raising ahead of it.

        Returns:
            List of human-readable error messages, empty when the
            configuration is usable.
        """
        errors = []

        # In non-debug/non-test modes, ensure secrets are not default
        if not self.DEBUG and not self.TESTING:
            errors.extend(self._secret_errors())

        errors.extend(self._domain_errors())
        errors.extend(self._database_errors())
        errors.extend(self._deployed_backend_errors())

        errors.extend(self._bounds_errors())
        errors.extend(self._redis_errors())
        errors.extend(self._numeric_errors())
        errors.extend(self._mail_errors())
        errors.extend(self._confirmation_errors())
        errors.extend(self._log_level_errors())
        errors.extend(self._language_errors())
        errors.extend(self._journal_name_errors())

        return errors


    def _journal_name_errors(self) -> List[str]:
        """
        Check that each journal name is a name and not a path.

        The three settings are joined to ``LOG_DIR`` and given a ``.log``
        suffix, with nothing in between looking at them. A name carrying a
        separator therefore writes outside the log directory --
        ``LOG_FILENAME=../../etc/cron.d/whatever`` is a file the
        application creates and appends to for as long as it runs -- and
        one carrying a directory that does not exist fails every write
        instead, which the failover machinery turns into a silent
        ``dropped_calls`` rather than a startup error.

        It reaches further than the writing. The rotator resolves these
        same three names into its configuration at start-up, so a name
        that points somewhere else takes ``rotate`` and ``create`` along
        with it -- a mistyped variable would have logrotate renaming files
        in a directory nobody meant to name.

        Checked at start-up rather than defended at the join, because
        there is nothing sensible to do at the join: a deployment that
        asked for an impossible journal has to be told, not quietly given
        a different one. Which is also why this is a validation error and
        not a fallback to the default.

        Returns:
            List of human-readable error messages.
        """
        errors = []
        for setting in (
            "LOG_FILENAME", "AUDIT_LOG_FILENAME", "ERROR_LOG_FILENAME"
        ):
            name = getattr(self, setting, "")
            if not JOURNAL_NAME.match(name or ""):
                errors.append(
                    f"Invalid {setting}: {name!r} -- a journal is named by "
                    "letters, digits, dot, dash and underscore, starting "
                    "with a letter or a digit, and is not a path"
                )
        return errors


    def _bounds_errors(self) -> List[str]:
        """
        Check the settings that have to lie inside a fixed range.

        Returns:
            List of human-readable error messages.
        """
        errors = []

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

        return errors


    def _language_errors(self) -> List[str]:
        """
        Check that a language can actually be chosen.

        Both faults here are silent at runtime rather than loud: an empty
        list leaves the negotiator with nothing to match and a default
        outside the list makes every page fall back to a language the
        deployment did not offer. Neither raises anywhere -- the pages just
        come out in the wrong language, which nobody reports as a bug.

        Compared case-insensitively: language tags are case-insensitive by
        RFC 5646, and refusing to start over ``DEFAULT_LANGUAGE=EN`` would
        be pedantry rather than a check.

        Returns:
            List of human-readable error messages.
        """
        errors = []

        supported = [tag.strip().lower() for tag in self.SUPPORTED_LANGUAGES]
        supported = [tag for tag in supported if tag]

        if not supported:
            errors.append("SUPPORTED_LANGUAGES must name at least one language")
        elif self.DEFAULT_LANGUAGE.strip().lower() not in supported:
            errors.append(
                f"DEFAULT_LANGUAGE ({self.DEFAULT_LANGUAGE}) is not in "
                f"SUPPORTED_LANGUAGES ({', '.join(supported)})"
            )

        return errors


    def _log_level_errors(self) -> List[str]:
        """
        Check that the log level is one logging understands.

        Returns:
            List of human-readable error messages.
        """
        allowed_levels = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
        if self.LOG_LEVEL.upper() not in allowed_levels:
            return [
                f"Invalid LOG_LEVEL: {self.LOG_LEVEL} "
                f"(allowed: {', '.join(allowed_levels)})"
            ]

        return []


    def _secret_errors(self) -> List[str]:
        """
        Check the two secrets, without letting either stop the other checks.

        Both are plain settings here and properties on the deployed
        profiles, where an unset one raises rather than returning a
        default. The refusal is collected instead of leaving ``validate``,
        so a deployment missing one hears about the rest as well.

        Returns:
            List of human-readable error messages.
        """
        errors = []
        for attribute, env_name, default in (
            ("SECRET_KEY", "SECRET_KEY", self._default_secret_key),
            ("SHORT_CODE_SECRET_PEPPER", "SHORT_CODE_PEPPER", self._default_pepper),
        ):
            try:
                value = getattr(self, attribute)
            except ValueError as error:
                errors.append(str(error))
                continue

            if value == default:
                errors.append(
                    f"{env_name} is using default value – override in .env"
                )

        return errors


    def _redis_errors(self) -> List[str]:
        """
        Check that Redis has a URL to connect to when it is switched on.

        Demanded whatever the cache is doing: the rate limiter reads
        ``REDIS_URL`` even with ``CACHE_ENABLED=false``.

        Returns:
            List of human-readable error messages.
        """
        if not self.REDIS_ENABLED:
            return []

        try:
            url = self.REDIS_URL
        except ValueError as error:
            return [str(error)]

        if not url:
            return ["REDIS_URL must be set when REDIS_ENABLED=True"]

        return []


    def _domain_errors(self) -> List[str]:
        """
        Check that ``DOMAIN`` is a host and not a whole URL.

        ``BASE_URL`` puts a scheme in front of this value and hands the
        result out as the address of every short link, so a value copied
        out of a browser's address bar --
        ``DOMAIN=https://staging.example.com`` -- builds
        ``https://https://staging.example.com`` and every short link with
        it.

        Returns:
            List of human-readable error messages; empty when ``DOMAIN``
            is unset, since absence is a documented fallback rather than
            an error.
        """
        domain = self.domain_value
        if not domain:
            return []

        if "://" in domain:
            return [
                f"DOMAIN must be a host name, not a URL: {domain!r} carries "
                "a scheme, which BASE_URL adds itself -- the two produce "
                "'https://https://...'. Use the host alone"
            ]

        if "/" in domain:
            return [
                f"DOMAIN must be a host name, not a path: {domain!r} -- "
                "short codes are served from the root, so a path here "
                "builds addresses that resolve to nothing"
            ]

        return []


    def validate_database(self) -> None:
        """
        Validate only the settings that decide which database is opened.

        A migration needs the connection string and nothing else; asking
        it to pass ``validate()`` in full would let mail, secrets or the
        domain stop ``alembic upgrade head``, and a migration reads none
        of them.

        The checks themselves are not skipped: they live in
        ``_database_errors`` and ``validate()`` runs them too, so there is
        one list and not a second one drifting behind it.

        Raises:
            ValueError: If any of the database settings is unusable.
        """
        errors = self._database_errors()
        if errors:
            raise ValueError("Configuration errors:\n - " + "\n - ".join(errors))


    def _database_errors(self) -> List[str]:
        """
        Check the settings that name the database to connect to.

        Returns:
            List of human-readable error messages (empty when the database
            settings are sane).
        """
        errors = []

        # A URL that will not parse, refused here rather than at whichever
        # command reaches it first. ``make_url`` raises ``ArgumentError``,
        # which is not a ``ValueError``, so it travelled straight past the
        # handler in ``migrations/env.py`` written to turn a bad setting
        # into a sentence, so ``postgres//u:p@host/db`` -- one missing
        # colon -- would pass ``validate()`` and end ``alembic upgrade``
        # in a traceback.
        if self.DATABASE_URL:
            try:
                make_url(self.DATABASE_URL.strip())
            except Exception as error:
                errors.append(
                    f"DATABASE_URL cannot be parsed as a connection URL: "
                    f"{error}"
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

            # The host is the same hole and was not closed: `URL.create`
            # percent-encodes the user and the password but not the host,
            # so "db.internal/shortener?sslmode=disable" arrives as host
            # "db.internal", database "shortener" and an sslmode nobody
            # set -- while DATABASE_NAME and DATABASE_PORT, which say
            # otherwise, are silently dropped.
            illegal = [c for c in "?#@/" if c in (self.DATABASE_HOST or "")]
            if illegal:
                errors.append(
                    "DATABASE_HOST must not contain "
                    f"{', '.join(repr(c) for c in illegal)} -- a host is a "
                    "host; a name or an option written into it replaces the "
                    "settings that carry them and is not reported"
                )

        # For SQLite the name is a path, so "/" is legitimate and only two
        # shapes are refused. A "?" is lost when the name is rendered into
        # a URL and read back: `make_url("sqlite:///a?b.db").database` is
        # "a", because everything past the "?" is taken for a query
        # string. SQLite itself would have opened the file it was named --
        # `sqlite3.connect("a?b.db")` creates exactly that -- so the loss
        # happens in the URL round trip, and it is silent, because a
        # missing SQLite file is created rather than refused. Nothing else
        # needs refusing here: "#", "@", a space and "%" each open the
        # file they name.
        # A ".." climbs out of the root the path is anchored to; anchoring
        # is not a sandbox and was never meant to be one, but a setting
        # that quietly lands outside the project is the same class of
        # surprise as the one above. The shared-cache in-memory form
        # belongs in DATABASE_URL, which bypasses anchoring entirely:
        # SQLAlchemy needs "sqlite:///file::memory:?cache=shared&uri=true",
        # and without that "uri=true" it is a file by definition.
        if self.DATABASE_TYPE == "sqlite":
            name = self.DATABASE_NAME or ""
            if name != ":memory:":
                if "?" in name:
                    errors.append(
                        "DATABASE_NAME must not contain '?' -- everything "
                        "past it is read as a query string when the name "
                        "becomes a URL, and a different file is opened; "
                        "put a URI form in DATABASE_URL instead"
                    )
                if ".." in Path(name).parts:
                    errors.append(
                        "DATABASE_NAME must not contain '..' -- a relative "
                        "name is anchored to the project root, and this one "
                        "lands outside it"
                    )

        if self.DATABASE_TYPE not in ("sqlite", "postgresql"):
            errors.append(f"Unsupported DATABASE_TYPE: {self.DATABASE_TYPE}")

        return errors


    def _deployed_backend_errors(self) -> List[str]:
        """
        Hold a deployed profile to PostgreSQL, whatever named the database.

        ``DATABASE_TYPE`` defaults to ``sqlite`` and ``DATABASE_NAME`` to
        ``db_shortener``, so a deployment that configured neither comes up
        on a brand-new empty file under ``DATABASE_DIR`` and answers as if
        the data had never existed.

        What is checked is the backend the profile would connect to, not
        whether some setting was written, because every road to SQLite
        here ends in a database that is empty and silent about it: a file
        nobody named is created rather than refused, a relative path is
        read against a working directory that gunicorn, celery and the
        CLI do not share, and an in-memory URL gives each thread its own
        database and drops it with the process.

        SQLite remains the local backend: ``development`` may still take
        either, and a profile nobody named resolves to ``development``, so
        a refusal there would land on a developer rather than on a
        deployment.

        Deliberately not part of ``_database_errors``: that list is what a
        migration checks through ``validate_database``, and a migration
        has its own, narrower rule in ``migration_url``.

        Returns:
            List of human-readable error messages (empty when a deployed
            profile is on PostgreSQL, and for the local profiles).
        """
        if self.DEBUG or self.TESTING:
            return []

        try:
            backend = make_url(self.get_database_url()).get_backend_name()
        except Exception:
            # Not this check's to report. An unusable combination raises
            # out of get_database_url naming the setting, an unsupported
            # DATABASE_TYPE is already in _database_errors, and a string
            # that will not parse stops the engine loudly on first use.
            return []

        if backend == "postgresql":
            return []

        # The remedy has to fit where the database was actually named, or
        # it sends the operator round in a circle: "set
        # DATABASE_TYPE=postgresql with the DATABASE_* parts", said while
        # a SQLite DATABASE_URL is set, cannot be followed --
        # get_database_url returns that URL first and never reads a part.
        if self.DATABASE_URL:
            remedy = (
                "DATABASE_URL decides on its own while it is set, and the "
                "DATABASE_* parts are not read at all, so put a PostgreSQL "
                "URL there or clear it and set the parts"
            )
        else:
            remedy = (
                "Set DATABASE_TYPE=postgresql with the DATABASE_* parts, "
                "or give the whole connection URL in DATABASE_URL"
            )

        # Said only where it is true. Every other backend reaches this the
        # same way and is refused for the same reason, but none of them is
        # the empty file this check was written for.
        why = ""
        if backend == "sqlite":
            why = (
                " SQLite is the backend for development: outside it, every "
                "form of one is a database that starts empty and never "
                "says so."
            )

        return [
            "this profile runs on PostgreSQL, and the configuration names "
            f"{self.display_database_url}. {remedy}.{why}"
        ]


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
            ("VISIT_RETENTION_DAYS", self.VISIT_RETENTION_DAYS),
            ("SECURITY_EVENT_RETENTION_DAYS", self.SECURITY_EVENT_RETENTION_DAYS),
            # Non-negative rather than positive: zero is a working setting
            # here, and the only way to switch the header off behind a proxy
            # that sends its own. A negative one is the quiet failure --
            # `max-age` is `delta-seconds` in RFC 6797, so a browser reading
            # `max-age=-1` discards the whole header and the service is left
            # with no HSTS at all while its configuration says a year.
            ("HSTS_MAX_AGE", self.HSTS_MAX_AGE),
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

    def _mail_errors(self) -> List[str]:
        """
        Check the mail settings for combinations that cannot work.

        The failures worth catching here are the quiet ones -- a channel
        that looks configured and delivers nothing -- but not all of them
        are: several of these combinations fail loudly at the first
        message instead, and are refused at startup because that is the
        cheaper place to find out either way.

        The transport-level flags are checked whether or not the channel is
        enabled, because they are typos either way and cost nothing to
        catch. Everything after the early return -- where to submit, and
        what to authenticate with -- is only demanded once something
        intends to submit.

        Returns:
            List of human-readable error messages (empty when the mail
            settings are coherent).
        """
        import math
        import re

        errors = []

        if self.MAIL_USE_TLS and self.MAIL_USE_SSL:
            errors.append(
                "MAIL_USE_TLS and MAIL_USE_SSL are mutually exclusive -- "
                "STARTTLS inside an already encrypted connection is a "
                "protocol error, not extra protection"
            )

        if not 1 <= self.MAIL_PORT <= 65535:
            errors.append(
                f"MAIL_PORT must be between 1 and 65535, got {self.MAIL_PORT}"
            )

        timeout = self.MAIL_TIMEOUT
        if not math.isfinite(timeout) or timeout <= 0:
            errors.append(
                f"MAIL_TIMEOUT must be a positive finite number of seconds, "
                f"got {timeout}"
            )

        if not self.MAIL_ENABLED:
            return errors

        if not self.MAIL_HOST:
            errors.append("MAIL_HOST must be set when MAIL_ENABLED=True")

        if not self.MAIL_FROM:
            errors.append("MAIL_FROM must be set when MAIL_ENABLED=True")
        elif not re.match(EMAIL_PATTERN_RE, self.MAIL_FROM):
            # Checked against the same expression the domain uses, so the
            # sender cannot be a shape the service would refuse from a
            # user. Whitespace is the part that matters: this value becomes
            # a From header, and a newline in a header is an injection.
            errors.append(
                f"MAIL_FROM is not a valid address: {self.MAIL_FROM!r}"
            )

        if self.REQUIRE_MAIL_TLS and not (self.MAIL_USE_TLS or self.MAIL_USE_SSL):
            errors.append(
                "this profile requires MAIL_USE_TLS or MAIL_USE_SSL when "
                "MAIL_ENABLED=True -- a submission in the clear carries the "
                "confirmation link to anyone on the path"
            )

        if self.MAIL_USERNAME and not (self.MAIL_USE_TLS or self.MAIL_USE_SSL):
            errors.append(
                "MAIL_USERNAME is set with neither MAIL_USE_TLS nor "
                "MAIL_USE_SSL -- the password would cross the network in "
                "the clear, so the mailer refuses to send it"
            )

        if self.MAIL_PASSWORD and not self.MAIL_USERNAME:
            errors.append(
                "MAIL_PASSWORD is set without MAIL_USERNAME -- nothing "
                "authenticates, so the password is never used"
            )

        if self.MAIL_USERNAME and not self.MAIL_PASSWORD:
            # The mirror of the check above, and the one that actually
            # happens: a blank environment variable reads as unset, and
            # ``docker compose`` substitutes a blank for every ${VAR}
            # missing from the env file. A mislaid MAIL_PASSWORD therefore
            # starts cleanly and fails at authentication on every single
            # registration, which is the last place anyone looks.
            errors.append(
                "MAIL_USERNAME is set without MAIL_PASSWORD -- the "
                "submission server will refuse the login on every message"
            )

        return errors

    def _confirmation_errors(self) -> List[str]:
        """
        Check the two confirmation lifetimes against each other.

        Checked whether or not mail is enabled: the sweep that deletes
        unconfirmed accounts is run from the command line
        (``flask maintenance clean-unverified``) and does not ask whether
        anything was ever mailed.

        Returns:
            List of human-readable error messages (empty when the two
            lifetimes are coherent).
        """
        errors = []

        for name, value in (
            ("EMAIL_VERIFICATION_TTL_HOURS", self.EMAIL_VERIFICATION_TTL_HOURS),
            ("UNVERIFIED_ACCOUNT_TTL_HOURS", self.UNVERIFIED_ACCOUNT_TTL_HOURS),
        ):
            if value < 1:
                errors.append(
                    f"{name} must be a positive number of hours, got {value}"
                )

        # Checked apart from the two above because its unit is different,
        # and a message saying "positive number of hours" about a value in
        # minutes sends the reader to change the wrong variable.
        if self.PASSWORD_RESET_TTL_MINUTES < 1:
            errors.append(
                "PASSWORD_RESET_TTL_MINUTES must be a positive number of "
                f"minutes, got {self.PASSWORD_RESET_TTL_MINUTES}"
            )

        if self.UNVERIFIED_ACCOUNT_TTL_HOURS < self.EMAIL_VERIFICATION_TTL_HOURS:
            errors.append(
                "UNVERIFIED_ACCOUNT_TTL_HOURS must not be shorter than "
                "EMAIL_VERIFICATION_TTL_HOURS -- the account would be swept "
                "away while the link mailed to it is still valid, and the "
                "person following that link would be told it is invalid"
            )

        return errors
