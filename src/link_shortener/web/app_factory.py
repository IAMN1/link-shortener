import os

from flask import Flask
from flask_cors import CORS
from infrastructure.config.factory import get_config
from infrastructure.web.controllers.link_controller import LinkController
from infrastructure.web.dependency_injection import Container
from infrastructure.web.middleware.error_handler import ErrorHandlerMiddleware
from infrastructure.web.middleware.request_logging import \
    RequestLoggingMiddleware


def create_app() -> Flask:
    """Фабрика приложения Flask"""
    
    # Загрузка конфигурации
    env = os.environ.get("FLASK_ENV", "development")
    config = get_config(env)
    
    # Создание Flask приложения
    app = Flask(__name__)
    app.config.update(config.to_dict())
    
    # CORS
    CORS(app)
    
    # Инициализация контейнера зависимостей
    container = Container.create(config)
    
    # Инициализация контроллеров
    link_controller = LinkController(container.link_service)
    
    # Регистрация middleware
    RequestLoggingMiddleware(app, container.logger)
    ErrorHandlerMiddleware(app, container.logger)
    
    # Регистрация маршрутов
    register_routes(app, link_controller)
    
    # Логирование успешного запуска
    container.logger.info(
        "Application started",
        environment=env,
        debug=config.DEBUG
    )
    
    return app


def register_routes(app: Flask, controller: LinkController):
    """Регистрация маршрутов"""
    
    # API v1
    app.add_url_rule(
        '/api/v1/shorten',
        view_func=controller.create_short_link,
        methods=['POST']
    )
    
    app.add_url_rule(
        '/api/v1/links/<short_code>',
        view_func=controller.get_link_info,
        methods=['GET']
    )
    
    app.add_url_rule(
        '/api/v1/batch/shorten',
        view_func=controller.batch_create,
        methods=['POST']
    )
    
    app.add_url_rule(
        '/api/v1/stats',
        view_func=controller.get_stats,
        methods=['GET']
    )
    
    # Редирект
    app.add_url_rule(
        '/<short_code>',
        view_func=controller.redirect_to_original,
        methods=['GET']
    )


if __name__ == '__main__':
    app = create_app()
    app.run(
        host=app.config.get('HOST', '127.0.0.1'),
        port=app.config.get('PORT', 5000),
        debug=app.config.get('DEBUG', False)
    )