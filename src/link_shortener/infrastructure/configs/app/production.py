from link_shortener.infrastructure.configs.app.base import BaseConfig
from link_shortener.infrastructure.configs.app.env import (
    env_bool, env_int, env_str, read_env_for
)


class ProductionConfig(BaseConfig):
    """
    Configuration for production environment.
    All debug features are disabled, secrets must be provided via environment,
    and performance settings are tuned for high load.
    """

    DEBUG: bool = False
    TESTING: bool = False


    # --------------------------------------------------------------------------
    # Logging: less verbose, file-based
    # --------------------------------------------------------------------------
    LOG_LEVEL: str = env_str("LOG_LEVEL", "INFO")
    LOG_TO_CONSOLE: bool = env_bool("LOG_TO_CONSOLE", False)
    LOG_TO_FILE: bool = env_bool("LOG_TO_FILE", True)
    # LOG_DIR: str = '/var/log/link_shortener'  # typical Linux log path


    # --------------------------------------------------------------------------
    # Security: secrets are mandatory
    # --------------------------------------------------------------------------
    @property
    def SECRET_KEY(self) -> str:
        """Secret key must be set in environment."""

        # read_env() rather than os.environ.get(): a blank value has to count
        # as "not configured", otherwise production would happily sign tokens
        # with a key made of spaces.
        key = read_env_for(self, "SECRET_KEY")
        if not key:
            raise ValueError("SECRET_KEY must be set in environment")

        return key

    @property
    def SHORT_CODE_SECRET_PEPPER(self) -> str:
        """Pepper must be set in environment."""

        pepper = read_env_for(self, "SHORT_CODE_PEPPER")
        if not pepper:
            raise ValueError(
                "SHORT_CODE_PEPPER must be set in environment"
            )

        return pepper


    # --------------------------------------------------------------------------
    # Application settings
    # --------------------------------------------------------------------------
    HOST: str = env_str("HOST", "0.0.0.0")
    PORT: int = env_int("PORT", 8000)

    USE_HTTPS: bool = env_bool("USE_HTTPS", True)
    """Production is expected to be served over TLS, so this defaults to true."""

    @property
    def BASE_URL(self) -> str:
        """Base URL for production – uses DOMAIN environment variable if set."""

        if self.DOMAIN:
            scheme = "https" if self.USE_HTTPS else "http"
            return f"{scheme}://{self.DOMAIN}"
        return f"http://{self.HOST}:{self.PORT}/"


    # --------------------------------------------------------------------------
    # Limits
    # --------------------------------------------------------------------------
    BATCH_CREATE_LIMIT: int = env_int("BATCH_CREATE_LIMIT", 100)


    # --------------------------------------------------------------------------
    # Redis: enabled by default
    # --------------------------------------------------------------------------
    REDIS_ENABLED: bool = env_bool("REDIS_ENABLED", True)

    @property
    def REDIS_URL(self) -> str:
        """
        Redis URL, demanded only when Redis is actually switched on.

        The condition is not decoration. ``Flask.config.from_object`` reads
        every upper-case attribute, this property among them, so raising
        here aborts startup for anyone -- including a deployment that set
        ``REDIS_ENABLED=false`` on purpose. That combination passed
        ``validate()``, which skips the check when Redis is off, and then
        died in the application factory: the configuration declared itself
        valid and the service still would not start.

        No fallback URL, unlike staging: in production a silent default
        pointing at localhost is worse than an empty value, because the
        cache would appear configured and quietly cache nothing.

        Returns:
            The configured URL, or an empty string when Redis is off.

        Raises:
            ValueError: If Redis is enabled and no URL is configured.
        """
        url = read_env_for(self, "REDIS_URL")
        if self.REDIS_ENABLED and not url:
            raise ValueError(
                "REDIS_URL must be set in environment when REDIS_ENABLED=True"
            )
        return url or ""


    # --------------------------------------------------------------------------
    # Alembic: strictly enforced in production
    # --------------------------------------------------------------------------
    USE_ALEMBIC: bool = env_bool("USE_ALEMBIC", True)

    # --------------------------------------------------------------------------
    # Security: cookies should be secure in production
    # --------------------------------------------------------------------------
    COOKIE_SECURE: bool = env_bool("COOKIE_SECURE", True)
    SESSION_COOKIE_SECURE: bool = env_bool("SESSION_COOKIE_SECURE", True)


    # --------------------------------------------------------------------------
    # Mail: submission must be encrypted
    # --------------------------------------------------------------------------
    REQUIRE_MAIL_TLS: bool = True


    # --------------------------------------------------------------------------
    # Database: no SQL echo in production
    # --------------------------------------------------------------------------
    SQLALCHEMY_ECHO: bool = env_bool("SQLALCHEMY_ECHO", False)

    # --------------------------------------------------------------------------
    # Auto-seed roles: disabled – all DB changes via migrations
    # --------------------------------------------------------------------------
    AUTO_SEED_ROLES: bool = env_bool("AUTO_SEED_ROLES", False)
    """
    In production, we strictly control DB schema and data via migrations.
    Automatic seeding is disabled to prevent accidental changes.
    The profile only sets the default – it stays overridable via env var,
    like every other documented setting.
    """


    def validate(self) -> None:
        """Enforce presence of required environment variables."""
        super().validate()
        # Force property evaluation to ensure required environment variables are set.
        _ = self.SECRET_KEY
        _ = self.SHORT_CODE_SECRET_PEPPER
        _ = self.get_database_url()
        
        if self.REDIS_ENABLED:
            _ = self.REDIS_URL

        # self.DOMAIN, not os.environ: the field already treats a blank
        # value as unset, and validate() must agree with what BASE_URL will see.
        if not self.DOMAIN:
            raise ValueError("DOMAIN environment variable must be set in production")
