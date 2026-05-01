import atexit
import os

from flask import Flask, redirect
from flask_cors import CORS

from link_shortener.infrastructure import (
    LoggingSettings,
    Container,
    get_config,
    setup_logging,
    register_flask_commands,
    seed_base_roles
)

from link_shortener.web.controllers.api_controller import ApiController
from link_shortener.web.controllers.frontend_controller import FrontendController
from link_shortener.web.middleware.authentication import AuthenticationMiddleware
from link_shortener.web.middleware.error_handler import ErrorHandlerMiddleware
from link_shortener.web.middleware.rate_limit import RateLimitMiddleware
from link_shortener.web.middleware.request_logging import RequestLoggingMiddleware
from link_shortener.web.utils import create_request_context

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
        # Load configuration from environment
        env = os.environ.get("FLASK_ENV", "development")
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
    # CORS
    # ------------------------------------------------------------------
    CORS(app)

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
            db_manager = container.get_db_manager()
            with db_manager.session() as session:
                seed_base_roles(session)

    # ------------------------------------------------------------------
    # Register Middlewares (order matters)
    # ------------------------------------------------------------------
    ## 1. Request logging (generates request_id)
    RequestLoggingMiddleware(app, container.get_logger(RequestLoggingMiddleware.__module__))
    ## 2. Authentication (loads current_user into g)
    AuthenticationMiddleware(
        app,
        container.get_authentication_service(),
        container.get_uow_factory()
    )
    ## 3. Error handling
    ErrorHandlerMiddleware(app, container.get_logger(ErrorHandlerMiddleware.__module__))
    ## 4. Rate limiting
    RateLimitMiddleware(app, container.get_rate_limiter())

    # ------------------------------------------------------------------
    # Register Controllers (Blueprints)
    # ------------------------------------------------------------------
    api_controller = ApiController(container.get_link_service())
    frontend_controller = FrontendController(container.get_link_service())

    app.register_blueprint(api_controller.bp)
    app.register_blueprint(frontend_controller.bp)

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
        """Simple health check endpoint."""
        return {"status": "healthy"}, 200

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

    if app.config.get("USE_ALEMBIC", True) and app.config.get("AUTO_SEED_ROLES", True):
        logger.warning(
            "Both USE_ALEMBIC and AUTO_SEED_ROLES are enabled. "
            "Roles are already seeded by the Alembic migration. "
            "Consider setting AUTO_SEED_ROLES=False to avoid redundant work."
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
