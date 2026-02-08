"""Экспорт всех интерфейсов доменного слоя"""

from .cache.abc_cache import ICacheClient
from .database.abc_repository import ILinkRepository
from .logger.abc_logger import ILogger
from .utils.abc_code_generator import ICodeGenerator
from .utils.abc_url_validator import IUrlValidator

__all__ = [
    "ICacheClient",
    "ILinkRepository",
    "ILogger",
    "ICodeGenerator",
    "IUrlValidator",
]
