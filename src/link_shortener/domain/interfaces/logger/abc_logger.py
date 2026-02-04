"""
Порт/Интерфейс для логирования
"""

from abc import ABC, abstractmethod
from typing import Any, Optional


class ILogger(ABC):
    """Интерфейс для логирования"""
    
    @abstractmethod
    def bind(self, **kwargs: Any) -> 'ILogger':
        """
        Привязывает контекст к логгеру и возвращает новый экземпляр
        """
        pass
    
    @abstractmethod
    def log(self, level: str, message: str, **kwargs: Any) -> None:
        """обощенное логирование"""
        pass

    @abstractmethod
    def debug(self, message: str, **kwargs: Any) -> None:
        """Запись отладочного сообщения"""
        pass

    @abstractmethod
    def info(self, message: str, **kwargs: Any) -> None:
        """Запись информационного сообщения"""
        pass

    @abstractmethod
    def warning(self, message: str, **kwargs: Any) -> None:
        """Запись предупреждения"""
        pass

    @abstractmethod
    def error(self, message: str, **kwargs: Any) -> None:
        """Запись ошибки"""
        pass

    @abstractmethod
    def exception(self, message: str, exc_info: Optional[Exception]= None, **kwargs: Any) -> None:
        """Запись исключения с трассировкой"""
        pass

