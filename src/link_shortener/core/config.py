import logging
import os
import secrets
from dotenv import load_dotenv

load_dotenv()


class BaseConfig:
    SHORT_CODE_LENGTH = 7
    DEBUG = True

    # logging settings
    LOG_DIR = os.environ.get('LOG_DIR', 'logs')
    # имя будет дополненно датой
    LOG_FILENAME = 'link_shortener'
    LOG_LEVEL = logging.INFO
    LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
    LOG_MAX_BYTES = 10 * 1024 * 1024 # 10 MB
    LOG_BACKUP_FILES_COUNT = 5
    LOG_TO_CONSOLE = True
    LOG_TO_FILE = True

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

    # Redis cache settings
    REDIS_ENABLED = os.environ.get('REDIS_ENABLED', True)
    REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    REDIS_CACHE_TTL = int(os.environ.get('REDIS_CACHE_TTL', 24 * 60 * 60)) # 24h
    REDIS_CACHE_TTL_STATS = int(os.environ.get('REDIS_CACHE_TTL_STATS', 5 * 60)) # 5m 

    # add redis_cache_prefix ????

    # TODO add monitoring

class DevelopmentConfig(BaseConfig):
    DEBUG = True
    
    LOG_LEVEL = logging.DEBUG
    LOG_TO_CONSOLE = True
    LOG_TO_FILE = False

    REDIS_ENABLED = os.environ.get('REDIS_ENABLED', True)   
    
class TestConfig:
    TESTING = True
    
    LOG_LEVEL = logging.WARNING  # В тестах меньше шума
    LOG_TO_CONSOLE = False
    LOG_TO_FILE = False

    DATABASE_URL = os.environ.get('DATABASE_URL_TEST') or 'sqlite:///test.db'

    REDIS_ENABLED = False

class ProductionConfig(BaseConfig):
    DEBUG = False

    LOG_LEVEL = logging.INFO
    LOG_TO_CONSOLE = False
    LOG_TO_FILE = True
    # LOG_DIR = '/var/log/link_shortener'  # Стандартный путь для логов в Linux

    SECRETS_KEY = os.environ['SECRET_KEY']    
    
    # POSTGRESQL IN PROD
    DATABASE_URL = os.environ['DATABASE_URL']

    # Настройки БД для высокой нагрузки
    DATABASE_POOL_SIZE = int(os.environ.get('DATABASE_POOL_SIZE', 50))
    DATABASE_MAX_OVERFLOW = int(os.environ.get('DATABASE_MAX_OVERFLOW', 20))

    # Redis Cache
    REDIS_ENABLED = os.environ.get('REDIS_ENABLED', True)
    REDIS_URL = os.environ.get('REDIS_URL', 'redis://redis:6379/0')

