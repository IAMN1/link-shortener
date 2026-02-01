from flask import Flask, g, redirect
from flask_cors import CORS


from link_shortener.application.services.link_service import LinkService
from link_shortener.infrastructure.web.error_handlers import register_error_handlers
from link_shortener.infrastructure.core.logging_config import setup_logging
from link_shortener.infrastructure.cache.cache_client import RedisCacheClient
from link_shortener.infrastructure.database.database_manager import Database
from link_shortener.infrastructure.database.repositories.sqlalchemy_link_repository import SQLAlchemyLinkRepository
from link_shortener.infrastructure.utils.short_code_generator import HashBasedGenerator
from link_shortener.infrastructure.utils.url_validators import UrlValidator
from link_shortener.infrastructure.web.api.v1 import create_api_v1_blueprint
from link_shortener.infrastructure.web.frontend import create_frontend_blueprint
from link_shortener.infrastructure.web.middleware.request_logging import init_middleware_request_logging

def create_app(config = None):
    """
    Фабричный метод создания приложения Flask
    """
    app = Flask(__name__)
    app.config.from_object(config)

    setup_logging(app)
    app.logger.info(f'Запуск приложения в среде {app.config.FLASK_ENV}')
    app.logger.info(f'Конфигурация: {app.config.__class__.__name__}')

    # 1. Инициализация инфраструктурных зависимостей
    ## База данных
    try:
        database = Database(database_url=config.DATABASE_URL, echo=config.DEBUG).connect()
        app.logger.info('База данных успешно инициализирована')
    except Exception as e:
        app.logger.critical('Проблема при инициализации базы данных', error=str(e))
        database = None
    

    ## Cache
    cache = None
    if config.REDIS_ENABLED:
        try:

            cache = RedisCacheClient.from_config(config)
            app.logger.info('Redis кэш успешно инициализирован')
        except Exception as e:
            app.logger.error('Проблема при инициализации кэширования Redis', error=str(e))
            cache = None
    else:
        app.logger.warning('Redis кэш отключен')


    # 2. Создание реализаций интерфейсов/портов
    if database:
        link_repository = SQLAlchemyLinkRepository(database=database)
    else:
        app.logger.critical('Не возможно создать репозиторий без Базы данных!')
        link_repository = None
    
    # 3. Создание утилит с конфигурацией
    code_generator = HashBasedGenerator(
        code_length=config.SHORT_CODE_LENGTH,
        pepper=config.SHORT_CODE_SECRET_PEPPER
    )
    url_validator = UrlValidator(
        max_url_length=config.MAX_URL_LENGTH,
        allowed_schemes=config.ALLOWED_SHEMES
    )

    # 4. Создание сервисов
    try:
        link_service = LinkService(
            repository=link_repository,
            cache_client=cache,
            cache_ttl=config.REDIS_CACHE_TTL,
            cache_ttl_stats=config.REDIS_CACHE_TTL_STATS,
            code_generator=code_generator,
            url_validator=url_validator,
            base_url=config.BASE_LINK,
            batch_limit=config.BATCH_CREATE_LIMIT
        )
        app.logger.info('Сервис управления ссылкой успешно инициализирован')
    except Exception as e:
        app.logger.critical('Ошибка при инициализации сервиса управления ссылкой', error=str(e))
        link_service = None

    # 5. Сохранение зависимостей в приложении
    app.database = database
    app.cache = cache
    app.link_service = link_service

    # 6. Настройка Flask
    # CORS для API
    CORS(app)
    app.logger.debug("CORS инициализирован")

    # 7. Middleware для логирования запросов
    init_middleware_request_logging(app)
    app.logger.info("Middleware для логирования запросов инициализирован")
    
    # 8. Установка сервиса в контекст запроса
    @app.before_request
    def before_request():
        """Устанавливает зависимости в контекст запроса"""
        g.link_service = app.link_service

    # 9. Регистрация Blueprints
    try:
        if link_service:
            # API-BP
            api_v1_bp = create_api_v1_blueprint(link_service)
            app.register_blueprint(api_v1_bp)
            app.logger.info('API blueprint registered')

            ## Frontend BP
            frontend_bp = create_frontend_blueprint(link_service)
            app.register_blueprint(frontend_bp)
            app.logger.info('Frontend blueprint registered')
        else:
            app.logger.warning('Невозможно зарегистрировать blueprints без инициализированного сервса')
    except Exception as e:
        app.logger.error('Ошибка при регистрации blueprints', error=str(e))

    # 10. Регистрация endpoints
    ## Endpoint for redirect 
    app.route('/<short_code>', methods=['GET'])
    def redirect_to_original(short_code: str):
        """редирект по на исходный URL"""
        try:
            if not link_service:
                return "service unvailable", 503
            
            original_url = link_service.get_original_url_for_refirect(short_code)
            app.logger.info(f'redirect: {short_code} -> {original_url[:50]}')
            return redirect(original_url, code=302)
        
        except Exception:
            # Проброс ошибки для обработки в error_handlers
            raise
    
    ## Endpoint for Health Check
    @app.route('/health', methods=['GET'])
    def health():
        """проверка здоровья приложения"""
        health_status = {
            'status': 'healthy',
            'database': 'connected' if database else 'disconnected',
            'cache': 'connected' if cache else 'disconnected',
            'service': 'available' if link_service else 'unavailable'
        }
        
        if database and cache and link_service:
            return health_status, 200
        else:
            health_status['status'] = 'degraded'
            return health_status, 503
    
    # 11. Регистрация обработчиков ошибок
    register_error_handlers(app)
    app.logger.info('Обработчики ошибок успешно зарегистрированы')


    # 12. Очистка ресурсов
    @app.teardown_appcontext
    def teardown_database(exception=None):
        """Закрывает соединение с БД при завершении контекста"""

        # Cache
        if hasattr(app, 'cache') and app.cache:
            try:
                app.cache.close()
                app.logger.debug('Redis cache closed')
            except Exception as e:
                app.logger.error('Ошибка при закрытии соединения кэша', error=str(e))

        # DB
        if hasattr(app, 'database'):
            try:
                app.database.close()
                app.logger.debug("Сессия базы данных закрыта")
            except Exception as e:
                app.logger.error('Error closing database connection', error=str(e))
        
        if exception:
            app.logger.error(f'Error during teardown: {exception}')
    

    app.logger.info('Flask application initialized successfully')
    return app