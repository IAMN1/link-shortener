from typing import Optional

from ..interfaces.logger.abc_logger import ILogger


class BaseService:
    """Базовый класс для всех доменных сервисов"""

    def __init__(self, logger: Optional[ILogger] = None):
        self._logger = logger
    
    def _log_debug(self, message: str, **kwargs) -> None:
        """Безопасное логирование отладки"""
        if self._logger:
            self._logger.debug(message, **kwargs)
    
    def _log_info(self, message: str, **kwargs) -> None:
        """Безопасное логирование информации"""
        if self._logger:
            self._logger.info(message, **kwargs)
    
    def _log_warning(self, message: str, **kwargs) -> None:
        """Безопасное логирование предупреждений"""
        if self._logger:
            self._logger.warning(message, **kwargs)
    
    def _log_error(self, message: str, **kwargs) -> None:
        """Безопасное логирование ошибок"""
        if self._logger:
            self._logger.error(message, **kwargs)