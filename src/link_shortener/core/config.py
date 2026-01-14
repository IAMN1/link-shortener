import os
import secrets
from dotenv import load_dotenv

load_dotenv()


class BaseConfig:
    SHORT_CODE_LENGTH = 7
    DEBUG = True

    # Security App
    SECRETS_KEY = os.environ.get('SECRET_KEY') or 'SECRET-KEY'
    SHORT_CODE_SECRET_PEPPER = os.environ.get('SHORT_CODE_PEPPER') or secrets.token_hex(32)

    # App settings
    HOST = os.environ.get('HOST') or 'localhost'
    PORT = os.environ.get('PORT') or 5000
    BASE_LINK = f'{HOST}:{PORT}/'

    # Security URL
    ALLOWED_SHEMES = ['http', 'https', 'ftp']
    MAX_URL_LENGTH = 2048

    # Limits
    MAX_REQUESTS_PER_MINUTE = 100
    BATH_CREATE_LIMIT = 100 # Макс URL за один пакетный запрос

    # Database settings
    DATABASE_URL = os.environ.get('DATABASE_URL') or 'sqlite:///dev.db'
    if DATABASE_URL.startswith('postgresql://'):
        # Настройки пула соединений для PostgreSQL
        DATABASE_POOL_SIZE = int(os.environ.get('DATABASE_POOL_SIZE', 20))
        DATABASE_MAX_OVERFLOW = int(os.environ.get('DATABASE_MAX_OVERFLOW', 10))
        DATABASE_POOL_RECYCLE = int(os.environ.get('DATABASE_POOL_RECYCLE', 3600))

    # TODO add redis for cache
    # REDIS_URL = 
    # CACHE_TTL = 

    # TODO add monitoring

class DevelopmentConfig(BaseConfig):
    DEBUG = True
    
class TestConfig:
    TESTING = True
    DATABASE_URL = os.environ.get('DATABASE_URL_TEST') or 'sqlite:///test.db'

class ProductionConfig(BaseConfig):
    DEBUG = False

    SECRETS_KEY = os.environ['SECRET_KEY']    
    
    # POSTGRESQL IN PROD
    DATABASE_URL = os.environ['DATABASE_URL']

    # Настройки БД для высокой нагрузки
    DATABASE_POOL_SIZE = int(os.environ.get('DATABASE_POOL_SIZE', 50))
    DATABASE_MAX_OVERFLOW = int(os.environ.get('DATABASE_MAX_OVERFLOW', 20))

