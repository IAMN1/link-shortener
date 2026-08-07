import atexit
import os

from flask import Flask, redirect
from flask_cors import CORS

from link_shortener.infrastructure import (
    LoggingSettings,
    Container,
    ConfigFactory,
    get_config,
    setup_logging,
    register_flask_commands,
    seed_base_roles
)

from link_shortener.web.controllers.admin_api_controller import AdminApiController
from link_shortener.web.controllers.api_controller import ApiController
from link_shortener.web.controllers.auth_controller import AuthController
from link_shortener.web.controllers.dashboard_controller import DashboardController
from link_shortener.web.controllers.frontend_controller import FrontendController
from link_shortener.web.middleware.authentication import AuthenticationMiddleware
from link_shortener.web.middleware.csrf import CsrfProtectionMiddleware
from link_shortener.web.middleware.error_handler import ErrorHandlerMiddleware
from link_shortener.web.middleware.rate_limit import RateLimitMiddleware
from link_shortener.web.middleware.request_logging import RequestLoggingMiddleware
from link_shortener.web.security.context import create_request_context

RBAC_TABLES = ("roles", "permissions")
"""Tables ``seed_base_roles`` writes to.

Their absence is the ordinary state of a database nobody has migrated yet,
which is a step the documented setup goes through on purpose: create, then
migrate, then seed.
"""


def _seed_base_roles_if_ready(container) -> None:
    """
    Seed the base roles, unless the schema is not in place yet.

    Startup seeding runs in every process, CLI invocations included. On a
    database without tables the attempt used to be reported as a failed
    seed, so every single command against a fresh database greeted the
    operator with a warning carrying a driver error -- for a state that is
    expected and that the next command fixes. An empty schema is now stated
    plainly and told what to do about it; a real failure (unreachable
    database, refused permission, malformed YAML) still warns.

    Must be called inside an application context.

    Args:
        container: DI container providing the database manager and logger.
    """
    logger = container.get_logger(__name__)

    try:
        db_manager = container.get_db_manager()
        missing = db_manager.missing_tables(RBAC_TABLES)
        if missing:
            logger.info(
                "Skipping role seeding: database schema is not initialised",
                missing_tables=", ".join(missing),
                next_step="flask alembic upgrade head && flask db load-base-roles",
            )
            return

        with db_manager.session() as session:
            seed_base_roles(session)
    except Exception as e:
        logger.warning("AUTO_SEED_ROLES failed", error=str(e))


def create_app(config=None) -> Flask:
    """
    Application factory.

    Args:
        config: Optional configuration object. If not provided, the config
            is loaded from the environment (``FLASK_ENV``).

    Returns:
        A fully configured Flask application.
    """

    if config is None:
        # Resolve the profile through the factory so that the same rules apply
        # everywhere: FLASK_ENV is case-insensitive and may come from `.env`.
        # Reading os.environ directly here used to make `FLASK_ENV=Production`
        # fail with "Unknown environment" while get_config() accepted it.
        env = ConfigFactory.resolve_env()
        config = get_config(env)
    else:
        env = getattr(config, "ENV", 'custom')

    # ------------------------------------------------------------------
    # Create Flask app
    # ------------------------------------------------------------------
    app = Flask(__name__)
    app.config.from_object(config)

    # ------------------------------------------------------------------
    # Setup logging
    # ------------------------------------------------------------------
    logging_settings = LoggingSettings(
        log_dir=app.config.get("LOG_DIR", "logs"),
        log_file_name=app.config.get("LOG_FILENAME", "link_shortener"),
        audit_log_filename=app.config.get("AUDIT_LOG_FILENAME", "audit"),
        error_log_filename=app.config.get("ERROR_LOG_FILENAME", "error"),
        log_date_format=app.config.get("LOG_DATE_FORMAT", "%Y-%m-%d %H:%M:%S"),
        log_to_console=app.config.get("LOG_TO_CONSOLE", True),
        log_to_file=app.config.get("LOG_TO_FILE", False),
        log_level_str=app.config.get("LOG_LEVEL", "DEBUG"), 
        debug=app.config.get("DEBUG", False),
        sqlalchemy_log_level=app.config.get("SQLALCHEMY_LOG_LEVEL", "WARNING"),
        werkzeug_log_level=app.config.get("WERKZEUG_LOG_LEVEL", "WARNING"),
        logger_type=app.config.get("LOGGER_TYPE", "auto"),
        audit_enabled=app.config.get("AUDIT_ENABLED", True)
    )
    setup_logging(
        logging_settings, 
        logging_enabled=app.config.get("LOGGING_ENABLED", True), 
        audit_enabled=app.config.get("AUDIT_ENABLED", True)
    )

    # ------------------------------------------------------------------
    # Register CLI commands (must be done before first request)
    # ------------------------------------------------------------------
    register_flask_commands(app)

    # ------------------------------------------------------------------
    # CORS (supports cookie-based auth)
    # ------------------------------------------------------------------
    CORS(
        app,
        origins=app.config.get("CORS_ORIGINS", ["http://localhost:5000"]),
        supports_credentials=True,
        allow_headers=["Content-Type", "Authorization"],
        expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining", "Retry-After"],
    )

    # ------------------------------------------------------------------
    # Dependency Injection Container
    # ------------------------------------------------------------------
    container = Container(config)
    app.container = container

    # ------------------------------------------------------------------
    # Idempotent seeding of base roles & permissions (only if flag allows)
    # ------------------------------------------------------------------
    auto_load_db_roles = app.config.get("AUTO_SEED_ROLES", True)
    if auto_load_db_roles:
        with app.app_context():
            _seed_base_roles_if_ready(container)

    # ------------------------------------------------------------------
    # Register Middlewares (order matters)
    # ------------------------------------------------------------------
    ## 1. Request logging (generates request_id)
    RequestLoggingMiddleware(app, container.get_logger(RequestLoggingMiddleware.__module__))
    ## 2. Authentication (loads current_user into g)
    AuthenticationMiddleware(
        app,
        container.get_authentication_service(),
        container.get_authorization_service(),
        container.get_uow_factory(),
        container.get_logger(AuthenticationMiddleware.__module__)
    )
    ## 3. CSRF protection (guards cookie-authenticated writes)
    CsrfProtectionMiddleware(
        app,
        container.get_logger(CsrfProtectionMiddleware.__module__),
        container.get_authentication_service()
    )
    ## 4. Error handling
    ErrorHandlerMiddleware(app, container.get_logger(ErrorHandlerMiddleware.__module__))
    ## 5. Rate limiting
    RateLimitMiddleware(
        app,
        container.get_rate_limiter(),
        container.get_logger(RateLimitMiddleware.__module__),
    )

    # ------------------------------------------------------------------
    # Register Controllers (Blueprints)
    # ------------------------------------------------------------------
    link_service = container.get_link_service()
    admin_service = container.get_admin_service()
    authentication_service = container.get_authentication_service()
    authorization_service = container.get_authorization_service()
    login_uc = container.get_login_use_case()
    register_uc = container.get_register_use_case()

    api_controller = ApiController(link_service, admin_service, authorization_service)
    frontend_controller = FrontendController()
    admin_api_controller = AdminApiController(admin_service)
    dashboard_controller = DashboardController(link_service, admin_service)
    auth_controller = AuthController(authentication_service, login_uc, register_uc)

    app.register_blueprint(api_controller.bp)
    app.register_blueprint(frontend_controller.bp)
    app.register_blueprint(admin_api_controller.bp)
    app.register_blueprint(dashboard_controller.bp)
    app.register_blueprint(auth_controller.bp)

    # ------------------------------------------------------------------
    # Redirect route (short code resolver)
    # ------------------------------------------------------------------
    @app.route("/<short_code>", methods=["GET"])
    def redirect_to_original(short_code: str):
        """
        Handle redirect requests by short code.

        Extracts client IP and User-Agent for audit logging,
        then returns a redirect response to the original URL.
        """

        context = create_request_context()
        original_url = container.get_link_service().redirect(short_code, context)

        return redirect(original_url)

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------
    @app.route('/health', methods=['GET'])
    def health():
        """
        Liveness endpoint, also used by the container healthcheck.

        Reports unhealthy only for the database, because that is the one
        dependency the service cannot serve a single request without: the
        cache and the task queue both degrade to working fallbacks. Their
        state is still reported, so a degraded deployment is visible rather
        than silent.

        The whole answer is bounded by ``HEALTH_CHECK_TIMEOUT``. A component
        that runs out of budget is reported ``timeout`` rather than
        ``unavailable``: both mean "not usable", but only one of them tells
        the operator which dependency is hanging.

        ``status`` is ``healthy``, ``degraded`` or ``unhealthy``; the HTTP
        code is 200 or 503. They answer different questions -- see below.

        Returns:
            JSON body and 200 when the service can serve, 503 otherwise.
        """
        state = container.health_check.snapshot()

        def describe(name: str, ok: bool) -> str:
            """Render one component's state."""
            if name in state.timed_out:
                return "timeout"
            return "ok" if ok else "unavailable"

        components = {
            "database": describe("database", state.database),
            # "ok" would claim a working cache on a deployment that runs
            # without one.
            "cache": (
                describe("cache", state.cache)
                if state.cache_configured
                else "disabled"
            ),
            "task_queue": describe("task_queue", state.task_queue),
            # Not "ok"/"unavailable": the limiter is reachable or not, but
            # what matters to an operator is whether limits are on.
            "rate_limiter": (
                "enforcing" if state.rate_limiter else "not_enforcing"
            ),
        }

        # Three states, two response codes, on purpose. The code answers the
        # container's question -- "should this be restarted?" -- and for a
        # failed cache or broker the answer is no: a restart does not fix
        # them and does take down a service that still works. The body
        # answers the operator's question, which the code cannot.
        if not state.database:
            status = "unhealthy"
        elif all(value in ("ok", "disabled", "enforcing") for value in components.values()):
            status = "healthy"
        else:
            status = "degraded"

        return (
            {
                "status": status,
                "components": components,
            },
            200 if state.database else 503,
        )

    # ------------------------------------------------------------------
    # Cleanup on exit
    # ------------------------------------------------------------------
    def close_resources():
        """Close all managed resources (database connections, cache connections, etc.)"""
        if hasattr(app, 'container'):
            app.container.close()
    
    atexit.register(close_resources)

    # ------------------------------------------------------------------
    # Startup log
    # ------------------------------------------------------------------
    cache = container.get_cache()
    # Log final application state
    logger = container.get_logger(create_app.__module__)
    active_logger_name = container.get_active_logger_name()

    cache_type = getattr(cache, "cache_type", "unknown")

    if app.config.get("AUTO_SEED_ROLES", True):
        logger.info(
            "AUTO_SEED_ROLES is enabled. Basic roles and permissions will be ensured at startup."
        )

    # Said out loud, even where validate() tolerates it. The default is
    # generated once per process, so more than one worker means more than
    # one value: a token issued by one is rejected by the others, and cache
    # entries written by one are refused by the rest. The symptom is
    # intermittent 401s that read as a bug in authentication rather than as
    # a missing setting.
    generated = config.default_secrets_in_use()
    if generated:
        logger.warning(
            "Running on generated secrets; each worker process has its own",
            settings=", ".join(generated),
        )

    logger.info(
        "Application Fully initialized",
        env=env,
        debug=app.config.get("DEBUG", False),
        testing=app.config.get("TESTING", False),
        active_logger=active_logger_name,
        cache_type=cache_type,
        redis_enabled=app.config.get("REDIS_ENABLED", False),
        database_url=config.display_database_url,
        host=app.config.get("HOST", "unknown"),
        port=app.config.get("PORT", "unknown"),
    )

    return app
