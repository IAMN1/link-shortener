from link_shortener.infrastructure.configs.app.base import BaseConfig
from link_shortener.infrastructure.configs.app.env import (
    env_bool, env_int, env_str, is_unset, read_env_for
)


class StagingConfig(BaseConfig):
    """
    Configuration for staging (pre-production) environment.
    Should closely mirror production settings but with debugging disabled.
    Secrets must be provided via environment variables.
    """

    DEBUG: bool = False
    TESTING: bool = False


    # --------------------------------------------------------------------------
    # Logging: typically more verbose than production for debugging
    # --------------------------------------------------------------------------
    LOG_LEVEL: str = env_str("LOG_LEVEL", "INFO")
    LOG_TO_CONSOLE: bool = env_bool("LOG_TO_CONSOLE", False)
    LOG_TO_FILE: bool = env_bool("LOG_TO_FILE", True)
    _default_log_dir: str = "/var/log/link_shortener/staging"
    """Overrides the base default only; ``LOG_DIR`` itself stays the
    property that anchors a relative value, so an operator who sets a
    relative one here gets the same directory the rest of the deployment
    uses rather than one per working directory."""


    # --------------------------------------------------------------------------
    # Security: enforce presence of secrets
    # --------------------------------------------------------------------------
    @property
    def SECRET_KEY(self) -> str:
        key = read_env_for(self, "SECRET_KEY")
        if not key:
            raise ValueError("SECRET_KEY must be set in environment")
        return key

    @property
    def SHORT_CODE_SECRET_PEPPER(self) -> str:
        pepper = read_env_for(self, "SHORT_CODE_PEPPER")
        if not pepper:
            raise ValueError("SHORT_CODE_PEPPER must be set in environment")
        return pepper


    # --------------------------------------------------------------------------
    # Redis: enabled by default for realistic testing
    # --------------------------------------------------------------------------
    REDIS_ENABLED: bool = env_bool("REDIS_ENABLED", True)
    
    @property
    def REDIS_URL(self) -> str:
        """Redis URL must be set in environment if Redis is enabled."""
        url = read_env_for(self, "REDIS_URL")
        if self.REDIS_ENABLED and not url:
            raise ValueError("REDIS_URL must be set in environment when REDIS_ENABLED=True")
        return url or "redis://localhost:6379/0"


    # --------------------------------------------------------------------------
    # Transport security: same as production
    # --------------------------------------------------------------------------
    # This profile says of itself that it mirrors production, and on these
    # three it did the opposite: they were not declared here, so they came
    # from BaseConfig, where all three are False for the sake of local
    # development without TLS. A staging deployment therefore sent its
    # session cookie over plain HTTP and built its links as http://.
    #
    # Still overridable by environment, for a staging host genuinely running
    # without TLS -- but that now has to be asked for rather than inherited.
    USE_HTTPS: bool = env_bool("USE_HTTPS", True)
    COOKIE_SECURE: bool = env_bool("COOKIE_SECURE", True)
    SESSION_COOKIE_SECURE: bool = env_bool("SESSION_COOKIE_SECURE", True)

    # Not overridable by environment, unlike the three above: those describe
    # how this host is reached, which a staging box may genuinely differ on.
    # This one describes how the service submits mail to somebody else's
    # server, and nothing about staging makes that safe in the clear.
    REQUIRE_MAIL_TLS: bool = True


    # --------------------------------------------------------------------------
    # Limits: same as production
    # --------------------------------------------------------------------------
    BATCH_CREATE_LIMIT: int = env_int("BATCH_CREATE_LIMIT", 100)


    # --------------------------------------------------------------------------
    # Auto-seed roles: disabled (seed once, deliberately)
    # --------------------------------------------------------------------------
    AUTO_SEED_ROLES: bool = env_bool("AUTO_SEED_ROLES", False)
    """
    Staging seeds roles as a deployment step, not on every application start.

    That step is `flask db load-base-roles`, run once after
    `alembic upgrade head`. It is not a migration: no revision seeds RBAC.
    Skip it and the `roles` table stays empty, which is not a visible
    failure -- the service starts and answers 401 to anonymous shortening.

    The profile only sets the default – it stays overridable via env var.
    """


    # --------------------------------------------------------------------------
    # Alembic: must be enabled in staging (mirrors production)
    # --------------------------------------------------------------------------
    USE_ALEMBIC: bool = env_bool("USE_ALEMBIC", True)


    def _collect_errors(self) -> list:
        """Enforce presence of required environment variables.

        The same override ``production`` carries. Two of this profile's
        demands are not settings and so are not part of the base checks:
        the database URL, which is assembled when something wants it, and
        ``DOMAIN``, whose absence is a fallback rather than an error.
        Unset, ``BASE_URL`` falls back to ``http://HOST:PORT/`` -- where
        the process binds rather than where the service is reached.

        The secrets are not read here: both are properties that refuse for
        themselves, and ``BaseConfig`` collects those refusals.

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
                "DOMAIN environment variable must be set in staging"
            )

        return errors
