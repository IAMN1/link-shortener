import os

import click
from flask import Flask, redirect, request, current_app
from flask.cli import with_appcontext
from flask_cors import CORS
from link_shortener.infrastructure.cache.memory_cache import InMemoryLinkCache
from link_shortener.infrastructure.cache.redis_cache import RedisLinkCache
from link_shortener.infrastructure.config.factory import get_config
from link_shortener.infrastructure.logging.config import setup_logging
from link_shortener.infrastructure.logging.handlers.failover import FailoverLogger
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
        # Загрузка конфигурации
        env = os.environ.get("FLASK_ENV", "development")
        config = get_config(env)
    else:
        env = getattr(config, "ENV", 'custom')

    # Создание Flask приложения
    app = Flask(__name__)
    app.config.from_object(config)

    # Настройка логирования
    setup_logging(app)

    app.cli.add_command(init_db_command)

    # CORS
    CORS(app)

    # Инициализация контейнера зависимостей
    container = Container(config)
    app.container = container

    # Регистрация middleware
    RequestLoggingMiddleware(app, container.get_logger())
    ErrorHandlerMiddleware(app, container.get_logger())

    # Создание контроллеров и регистрация блюпринтов
    api_controller = ApiController(container.get_link_service())
    frontend_controller = FrontendController(container.get_link_service())

    app.register_blueprint(api_controller.bp)
    app.register_blueprint(frontend_controller.bp)

    # маршрут для редиректа
    @app.route("/<short_code>", methods=["GET"])
    def redirect_to_original(short_code: str):
        """
        Handle redirect requests by short code.

        Extracts client IP and User-Agent for audit logging,
        then returns a redirect response to the original URL.
        """

        # Extract real client IP (handling proxies)
        user_ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()

        user_agent = request.user_agent.string if request.user_agent else None

        original_url = container.get_link_service().redirect(short_code, user_ip=user_ip, user_agent=user_agent)

        return redirect(original_url)

    # Health check
    @app.route('/health', methods=['GET'])
    def health():
        """Simple health check endpoint."""
        return {"status": "healthy"}, 200

    # Очистка ресурсов при завершении контекста
    @app.teardown_appcontext
    def shutdown_session(exception=None):
        """Close database connections when the app context ends."""
        container.close()

    # Финальное логирвоание состояния приложения
    logger = container.get_logger()
    cache = container.get_cache()

    # Определение типа кэша
    if isinstance(cache, RedisLinkCache):
        cache_type = "Redis"
    elif isinstance(cache, InMemoryLinkCache):
        cache_type = "InMemory"
    else:
        cache_type = "Disabled (NullCache)"
    
    # Определение активного логгера (Если это FailoverLogger)
    if isinstance(logger, FailoverLogger):
        active_logger = logger.get_current_logger_name()
    else:
        active_logger = type(logger).__name__

    # Логирование успешного запуска
    logger.info(
        "Application Fylly initialized",
        env=env,
        debug=app.config.get("DEBUG", False),
        testing=app.config.get("TESTING", False),
        active_logger=active_logger,
        cache_type=cache_type,
        redis_enabled=app.config.get("REDIS_ENABLED", False),
        database_url=app.config.get("DATABASE_URL", "unknown"),
        host=app.config.get("HOST", "unknown"),
        port=app.config.get("PORT", "unknown"),
    )

    return app
