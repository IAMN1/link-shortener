import os
from flask import Flask
from flask_cors import CORS

from link_shortener.core.config import (
    DevelopmentConfig,
    ProductionConfig,
    TestConfig
)
from link_shortener.core.logging_config import setup_logging
from link_shortener.middleware.request_logging import init_middleware_request_logging

PROD = 'PROD'
DEV = 'DEV'
TEST = 'TEST'

def create_app(config=None):
    """
    Фабрика приложения Flask
    """
    app = Flask(__name__)
    
    if config is None:
        env = os.environ.get('FLASK_ENV', DEV)
        if env == PROD:
            config = ProductionConfig
        elif env == TEST:
            config = TestConfig
        else:
            config = DevelopmentConfig
    
    app.config.from_object(config)

    setup_logging(app)
    app.logger.info(f'Запуск приложения в среде {env}')
    app.logger.info(f'Конфигурация: {config.__name__}')

    # CORS для API
    CORS(app)
    app.logger.debug("CORS инициализирован")

    # Middleware для логирования запросов
    init_middleware_request_logging(app)
    app.logger.info("Middleware для логирования запросов инициализирован")

    # DB
    with app.app_context():
        from link_shortener.database.database import init_db
        app.logger.info("Инициализация Базы Данных")
        init_db()
        app.logger.info("База данных успешно инициализирована")

    # BluePrints
    #app.register_blueprint(api_bp, url_prefix='/api')

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        """Закрывает соединение при завершении контекста"""
        from link_shortener.database.database import db_session
        if db_session:
            db_session.remove()
            app.logger.debug("Сессия базы данных закрыта")
        
        if exception:
            app.logger.error(f"Ошибка при завершении контекста: {exception}")

    return app

if __name__ == "__main__":
    app = create_app()
    
    app.logger.info(f"Запуск сервера на {app.config['HOST']}:{app.config['PORT']}")
    
    app.run(
        host=app.config['HOST'],
        port=app.config['PORT'],
        debug=app.config['DEBUG']
    )
        

