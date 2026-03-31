import atexit
import os

from flask import Flask, g, redirect, request
from flask_cors import CORS
from link_shortener.application import RequestContext
from link_shortener.infrastructure import (
    LoggingSettings,
    get_config,
    setup_logging,
    register_flask_commands,
)
from link_shortener.web.controllers.api_controller import ApiController
from link_shortener.web.controllers.frontend_controller import FrontendController
from link_shortener.web.dependency_injection import Container
from link_shortener.web.middleware.error_handler import ErrorHandlerMiddleware
from link_shortener.web.middleware.rate_limit import RateLimitMiddleware
from link_shortener.web.middleware.request_logging import RequestLoggingMiddleware

def create_app(config=None) -> Flask:
    """
    Application factory for creating and configuring a Flask instance.

    Args:
        config: Optional configuration object. If not provided, loads from environment.

    Returns:
        Flask: Configured Flask application
    """

    if config is None:
        # Load configuration from environment
        env = os.environ.get("FLASK_ENV", "development")
        config = get_config(env)
    else:
        env = getattr(config, "ENV", 'custom')

    # Create Flask application
    app = Flask(__name__)
    app.config.from_object(config)

    # Setup logging
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
        logger_type=app.config.get("LOGGER_TYPE", True),
        audit_enabled=app.config.get("AUDIT_ENABLED", True)
    )
    setup_logging(
        logging_settings, 
        logging_enabled=config.LOGGING_ENABLED, 
        audit_enabled=config.AUDIT_ENABLED
    )

    # Регистрация CLI-комманд
    register_flask_commands(app)

    # CORS
    CORS(app)

    # Initialize dependency injection container
    container = Container(config)
    app.container = container

    # Register middleware
    RequestLoggingMiddleware(app, container.get_logger(RequestLoggingMiddleware.__module__))
    ErrorHandlerMiddleware(app, container.get_logger(ErrorHandlerMiddleware.__module__))
    RateLimitMiddleware(app, container.get_rate_limiter())

    # Create controllers and register blueprints
    api_controller = ApiController(container.get_link_service())
    frontend_controller = FrontendController(container.get_link_service())

    app.register_blueprint(api_controller.bp)
    app.register_blueprint(frontend_controller.bp)

    # Redirect route
    @app.route("/<short_code>", methods=["GET"])
    def redirect_to_original(short_code: str):
        """
        Handle redirect requests by short code.

        Extracts client IP and User-Agent for audit logging,
        then returns a redirect response to the original URL.
        """

        context = RequestContext(
            request_id=g.get('request_id'),
            remote_addr=request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip(),
            user_agent=request.user_agent.string if request.user_agent else None,
            request_path=request.path,
            request_method=request.method
        )
        original_url = container.get_link_service().redirect(short_code, context)

        return redirect(original_url)

    # Health check
    @app.route('/health', methods=['GET'])
    def health():
        """Simple health check endpoint."""
        return {"status": "healthy"}, 200


    def close_resources():
        """Close all managed resources (database connections, cache connections, etc.)"""
        if hasattr(app, 'container'):
            app.container.close()
    
    atexit.register(close_resources)

    cache = container.get_cache()
    # Log final application state
    logger = container.get_logger(create_app.__module__)
    active_logger_name = container.get_active_logger_name()

    cache_type = getattr(cache, "cache_type", "unknown")

    # Логирование успешного запуска
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
