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

    # BluePrints
    #app.register_blueprint(api_bp, url_prefix='/api')

    return app

if __name__ == "__main__":
    app = create_app()
        

