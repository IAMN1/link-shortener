from link_shortener.infrastructure.config.factory import get_config
from link_shortener.infrastructure.web.flask_app_factory import create_app


if __name__ == "__main__":

    # Автоматическое получение конфигурации
    config = get_config(None)

    app = create_app(config)
    
    app.logger.info(f"Запуск сервера на {app.config['HOST']}:{app.config['PORT']}")
    
    app.run(
        host=app.config['HOST'],
        port=app.config['PORT'],
        debug=app.config['DEBUG']
    )
        

