import os
from dotenv import load_dotenv

load_dotenv()


class BaseConfig:
    SHORT_CODE_RANDOM_PART_LENGTH = 4
    SHORT_CODE_ID_PART_LENGTH = 3
    DEBUG = True

    # Security App
    SECRETS_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'

    # App settings
    HOST = os.environ.get('HOST') or 'localhost'
    PORT = os.environ.get('PORT') or 5000
    BASE_LINK = f'{HOST}:{PORT}/'

    # Security URL
    ALLOWED_SHEMES = ['http', 'https', 'ftp']
    MAX_URL_LENGTH = 2048

    # Limits
    MAX_REQUESTS_PER_MINUTE = 60

    # Database settings
    DATABASE_URL = os.environ.get('DATABASE_URL') or 'sqlite:///dev.db'
    # TODO add redis


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    

class TestConfig:
    TESTING = True
    SECRET_KEY = 'TEST-SECRET-KEY'

    DATABASE_URL = os.environ.get('DATABASE_URL_TEST') or 'sqlite:///test.db'

class ProductionConfig(BaseConfig):
    DEBUG = False

    SECRETS_KEY = os.environ['SECRET_KEY']
    
    # TODO add database

