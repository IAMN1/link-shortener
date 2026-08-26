from link_shortener.infrastructure.configs.app.base import BaseConfig
from link_shortener.infrastructure.configs.app.env import (
    env_bool, env_int, env_str, is_unset, read_env_for
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
    # A deployed profile turns an optional base setting into a mandatory one,
    # so a writeable attribute becomes a read-only property here. That
    # narrowing is the point of the profile, not an oversight.
    @property
    def SECRET_KEY(self) -> str:  # type: ignore[override]
        """Secret key must be set in environment."""

        # read_env() rather than os.environ.get(): a blank value has to count
        # as "not configured", otherwise production would happily sign tokens
        # with a key made of spaces.
        key = read_env_for(self, "SECRET_KEY")
        if not key:
            raise ValueError("SECRET_KEY must be set in environment")

        return key

    # A deployed profile turns an optional base setting into a mandatory one,
    # so a writeable attribute becomes a read-only property here. That
    # narrowing is the point of the profile, not an oversight.
    @property
    def SHORT_CODE_SECRET_PEPPER(self) -> str:  # type: ignore[override]
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
    # Inside a container anything narrower is invisible from outside,
    # however many ports are published. The mark below carries no test id on
    # purpose: given one, bandit suppresses the finding and complains in the
    # same breath that nothing fired on that line -- it looks for the finding
    # by the call's line and reports it by the literal's. The mark word
    # cannot appear in prose here either, because bandit reads whatever
    # follows it as a list of test ids.
    HOST: str = env_str("HOST", "0.0.0.0")  # nosec
    PORT: int = env_int("PORT", 8000)

    USE_HTTPS: bool = env_bool("USE_HTTPS", True)
    """Production is expected to be served over TLS, so this defaults to true."""

    # --------------------------------------------------------------------------
    # Limits
    # --------------------------------------------------------------------------
    BATCH_CREATE_LIMIT: int = env_int("BATCH_CREATE_LIMIT", 100)


    # --------------------------------------------------------------------------
    # Redis: enabled by default
    # --------------------------------------------------------------------------
    REDIS_ENABLED: bool = env_bool("REDIS_ENABLED", True)

    # A deployed profile turns an optional base setting into a mandatory one,
    # so a writeable attribute becomes a read-only property here. That
    # narrowing is the point of the profile, not an oversight.
    @property
    def REDIS_URL(self) -> str:  # type: ignore[override]
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


    def _collect_errors(self) -> list:
        """Add what a deployed profile demands beyond the base checks.

        Extends the base list rather than raising after it, so an operator
        learns about every missing setting in one run.

        Returns:
            List of human-readable error messages.
        """
        errors = super()._collect_errors()

        # Secrets and Redis are already collected by the base class, which
        # reads both through the properties this profile overrides and
        # keeps the message each raises.
        try:
            self.get_database_url()
        except ValueError as error:
            errors.append(str(error))

        # The parts that have defaults, demanded explicitly on a deployed
        # profile. ``DATABASE_HOST`` falls back to ``localhost`` and
        # ``DATABASE_NAME`` to ``db_shortener``, so a deployment naming
        # only ``DATABASE_TYPE=postgresql`` and a user would connect to a
        # server and a database nobody chose -- the same class of fault
        # ``_deployed_backend_errors`` exists for, on PostgreSQL rather
        # than on SQLite.
        if not self.DATABASE_URL and self.DATABASE_TYPE == "postgresql":
            for name in ("DATABASE_HOST", "DATABASE_NAME"):
                # Both halves are asked, because either one is a way of
                # saying it deliberately: the variable, or a profile that
                # pins the value as a class attribute. Only the value that
                # is still the inherited default *and* unnamed in the
                # environment is the one nobody chose.
                default = vars(BaseConfig)[name].default
                if getattr(self, name) == default and is_unset(
                    read_env_for(self, name)
                ):
                    errors.append(
                        f"{name} must be set when a deployed profile builds "
                        f"its connection from the DATABASE_* parts -- the "
                        f"default names a database nobody chose"
                    )

        # domain_value, not os.environ and not the raw field: it is what
        # BASE_URL builds from, so the check and the builder cannot
        # disagree about what counts as set.
        if not self.domain_value:
            errors.append(
                "DOMAIN environment variable must be set in production"
            )

        return errors
