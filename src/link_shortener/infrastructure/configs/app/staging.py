from link_shortener.infrastructure.configs.app.base import BaseConfig
from link_shortener.infrastructure.configs.app.env import (
    env_bool, env_int, env_str, read_env_for
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
    `alembic upgrade head`. It is not a migration: no revision seeds RBAC,
    though this comment and three others used to say so. Skip it and the
    `roles` table stays empty, which is not a visible failure -- the service
    starts and answers 401 to anonymous shortening.

    The profile only sets the default – it stays overridable via env var.
    """


    # --------------------------------------------------------------------------
    # Alembic: must be enabled in staging (mirrors production)
    # --------------------------------------------------------------------------
    USE_ALEMBIC: bool = env_bool("USE_ALEMBIC", True)
