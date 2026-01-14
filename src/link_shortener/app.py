import os
from flask import Flask
from flask_cors import CORS

from link_shortener.core.config import DevelopmentConfig, ProductionConfig, TestConfig

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

    # CORS для API
    CORS(app)

    # DB
    with app.app_context():
        from link_shortener.database.database import init_db
        init_db()

    # BluePrints
    #app.register_blueprint(api_bp, url_prefix='/api')

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        """Закрывает соединение при завершении контекста"""
        from link_shortener.database.database import db_session
        if db_session:
            db_session.remove()

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(
        host=app.config['HOST'],
        port=app.config['PORT'],
        debug=app.config['DEBUG']
    )
        

