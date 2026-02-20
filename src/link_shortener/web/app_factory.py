import os

from flask import Flask, redirect, request
from flask_cors import CORS
from link_shortener.infrastructure.config.factory import get_config
from link_shortener.infrastructure.core.logging_config import setup_logging
from link_shortener.web.controllers.api_controller import ApiController
from link_shortener.web.controllers.frontend_controller import FrontendController
from link_shortener.web.dependency_ingection import Container
from link_shortener.web.middleware.error_handler import ErrorHandlerMiddleware
from link_shortener.web.middleware.request_logging import RequestLoggingMiddleware


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

    # Создание Flask приложения
    app = Flask(__name__)
    app.config.from_object(config)

    # Настройка логирования
    setup_logging(app)

    # CORS
    CORS(app)

    # Инициализация контейнера зависимостей
    container = Container(config)

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
        
        if hasattr(container, '_db_manager') and container._db_manager:
            container._db_manager.close()

    # Логирование успешного запуска
    app.logger.info(
        "Application started", extra={"env": env}
    )

    return app
