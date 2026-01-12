import os
from dotenv import load_dotenv

load_dotenv()


class BaseConfig:
    # Security App
    SECRETS_KEY = os.environ.get('SECRETS_KEY') or 'dev-secret-key-change-in-production'

    # App settings
    BASE_URL = os.environ.get('BASE_URL') or 'http://localhost'
    BASE_PORT = os.environ.get('BASE_PORT') or 5000
    BASE_LINK = f'{BASE_URL}:{BASE_PORT}/'
    SHORT_CODE_RANDOM_PART_LENGTH = 4
    SHORT_CODE_ID_PART_LENGTH = 3

    # Security URL
    ALLOWED_SHEMES = ['http', 'https', 'ftp']
    MAX_URL_LENGTH = 2048

    # Limits
    MAX_REQUESTS_PER_MINUTE = 60

    # TODO add DB
    # TODO add redis


class DevelopmentConfig(BaseConfig):
    DEBUG = True

    # TODO add DEV DataBase

class TestConfig:
    TESTING = True
    SECRET_KEY = 'TEST-SECRET-KEY'
    # TODO add Testing DataBase

class ProductionConfig(BaseConfig):
    DEBUG = False

    SECRETS_KEY = os.environ['SECRETS_KEY']
    
    # TODO add database

