import os
import secrets
from typing import List, Optional
from urllib.parse import urlparse
import logging


class BaseConfig:
    DEBUG = True

    # ========== logging settings ==========
    LOG_DIR: str = os.environ.get('LOG_DIR', 'logs')
    # имя будет дополненно датой
    LOG_FILENAME: str = 'link_shortener'
    LOG_LEVEL = logging.INFO
    LOG_DATE_FORMAT: str = '%Y-%m-%d %H:%M:%S'
    LOG_MAX_BYTES: int = 10 * 1024 * 1024 # 10 MB
    LOG_BACKUP_FILES_COUNT: int = 5
    LOG_TO_CONSOLE: bool = True
    LOG_TO_FILE: bool = True

    # ========== Security App ==========
    SECRET_KEY: str = os.environ.get('SECRET-KEY') or secrets.token_hex(32)
    SHORT_CODE_SECRET_PEPPER: str = os.environ.get('SHORT_CODE_PEPPER') or secrets.token_hex(32)

    # ========== App settings ==========
    HOST: str = os.environ.get('HOST', 'localhost')
    PORT: int = int(os.environ.get('PORT', 5000))
    BASE_LINK: str = f'{HOST}:{PORT}/'

    ALLOWED_SHEMES: List[str] = ['http', 'https', 'ftp']
    MAX_URL_LENGTH: int = 2048
    SHORT_CODE_LENGTH = 7

    # ========== Limits ==========
    MAX_REQUESTS_PER_MINUTE: int = 100
    BATCH_CREATE_LIMIT: int = 100 # Макс URL за один пакетный запрос

    # ========== Database settings ==========
    DATABASE_URL: str = os.environ.get('DATABASE_URL', 'sqlite:///dev.db')

    @property
    def DATABASE_POOL_SIZE(self) -> int:
        if self.DATABASE_URL.startswith('postgresql://'):
            return int(os.environ.get('DATABASE_POOL_SIZE', 20))
        return 0
    
    @property
    def DATABASE_MAX_OVERFLOW(self) -> int:
        if self.DATABASE_URL.startswith('postgresql://'):
            return int(os.environ.get('DATABASE_MAX_OVERFLOW', 10))
        return 0
    
    @property
    def DATABASE_POOL_RECYCLE(self) -> int:
        if self.DATABASE_URL.startswith('postgresql://'):
            return int(os.environ.get('DATABASE_POOL_RECYCLE', 3600))
        return 0

    # ========== Redis cache settings ==========
    REDIS_ENABLED: int = os.environ.get('REDIS_ENABLED', False)
    REDIS_URL: str = os.environ.get('REDIS_URL', '-')
    REDIS_CACHE_TTL: int = int(os.environ.get('REDIS_CACHE_TTL', 0))
    REDIS_CACHE_TTL_STATS: int = int(os.environ.get('REDIS_CACHE_TTL_STATS', 0))
    REDIS_CACHE_PREFIX: str = os.environ.get('REDIS_CACHE_PREFIX', 'link_shortener')
    
    @property
    def REDIS_HOST(self) -> Optional[str]:
        try:
            parsed = urlparse(self.REDIS_URL)
            return parsed.hostname
        except Exception:
            return None

    @property
    def REDIS_PORT(self) -> Optional[int]:
        try:
            parsed = urlparse(self.REDIS_URL)
            return parsed.port or 6379
        except Exception:
            return None
    
    @property
    def REDIS_DB(self) -> Optional[int]:
        try:
            parsed = urlparse(self.REDIS_URL)
            path = parsed.path.strip('/')
            return int(path) if path.isdigit() else 0
        except Exception:
            return None

    # TODO add monitoring

    # ========== Validation Configuration ==========
    def validate(self) -> None:
        """Проверка конфигурации на корректность"""
        errors = []

        if not self.SECRET_KEY or self.SECRET_KEY == secrets.token_hex(32):
            errors.append("SECRET_KEY должен быть утсановлен в продакшене")
        
        for scheme in self. ALLOWED_SHEMES:
            if scheme not in ['http', 'https', 'ftp']:
                errors.append(f'Недопустимая схема URL: {scheme}')
        
        # ??? МБ вообще не нужно
        if self.MAX_URL_LENGTH > 2048:
            errors.append('MAX_URL_LENGTH не должен превышать 2048 символов')
        
        if self.REDIS_ENABLED and not self.REDIS_URL.startswith('redis://'):
            errors.append('REDIS_URL должен начинаться с "redis://"')
        
        if errors and not self.DEBUG:
            raise ValueError(f'Ошибки в конфигурации: {','.join(errors)}')
