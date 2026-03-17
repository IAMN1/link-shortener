import atexit
import os

import click
from flask import Flask, g, redirect, request, current_app
from flask.cli import with_appcontext
from flask_cors import CORS
from link_shortener.application.context import RequestContext
from link_shortener.infrastructure import InMemoryLinkCache, RedisLinkCache, LoggingSettings
from link_shortener.infrastructure.config.factory import get_config
from link_shortener.infrastructure.logging.config import setup_logging
from link_shortener.web.controllers.api_controller import ApiController
from link_shortener.web.controllers.frontend_controller import FrontendController
from link_shortener.web.dependency_injection import Container
from link_shortener.web.middleware.error_handler import ErrorHandlerMiddleware
from link_shortener.web.middleware.request_logging import RequestLoggingMiddleware


@click.command
@with_appcontext
def init_db_command():
    """Create database tables based on current models."""
    container = current_app.container
    db_manager = container.get_db_manager()

    try:
        db_manager.create_tables()
        click.echo("Database tables created successfully.")
    except Exception as e:
        click.echo(f"Error creating tables: {e}", err=True)
        raise


def create_app(config=None) -> Flask:
    """
    Application factory for creating and configuring a Flask instance.

    Args:
        config (_type_, optional): Optional configuration object. 
            If not provided, loads from environment.

    Returns:
        Flask: Configured Flask application.
    """

    if config is None:
        # Load configuration
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
        log_date_format=app.config.get("LOG_DATE_FORMAT", "%Y-%m-%d %H:%M:%S"),
        log_to_console=app.config.get("LOG_TO_CONSOLE", True),
        log_to_file=app.config.get("LOG_TO_FILE", False),
        log_level_str=app.config.get("LOG_LEVEL", "DEBUG"), 
        debug=app.config.get("DEBUG", False),
        sqlalchemy_log_level=app.config.get("SQLALCHEMY_LOG_LEVEL", "WARNING"),
        werkzeug_log_level=app.config.get("WERKZEUG_LOG_LEVEL", "WARNING"),
    )
    setup_logging(
        logging_settings, 
        logging_enabled=config.LOGGING_ENABLED, 
        audit_enabled=config.AUDIT_ENABLED
    )

    app.cli.add_command(init_db_command)

    # CORS
    CORS(app)

    # Initialize dependency injection container
    container = Container(config)
    app.container = container

    # Register middleware
    RequestLoggingMiddleware(app, container.get_logger(RequestLoggingMiddleware.__module__))
    ErrorHandlerMiddleware(app, container.get_logger(ErrorHandlerMiddleware.__module__))

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

    # Determine cache type
    if isinstance(cache, RedisLinkCache):
        cache_type = "Redis"
    elif isinstance(cache, InMemoryLinkCache):
        cache_type = "InMemory"
    else:
        cache_type = "Disabled (NullCache)"

    # Логирование успешного запуска
    logger.info(
        "Application Fully initialized",
        env=env,
        debug=app.config.get("DEBUG", False),
        testing=app.config.get("TESTING", False),
        active_logger=active_logger_name,
        cache_type=cache_type,
        redis_enabled=app.config.get("REDIS_ENABLED", False),
        database_url=app.config.get("DATABASE_URL", "unknown"),
        host=app.config.get("HOST", "unknown"),
        port=app.config.get("PORT", "unknown"),
    )

    return app
