from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class Logger(ABC):
    """Интерфейс логирования"""

    @abstractmethod
    def debug(self, message: str, **kwargs: Any) -> None:
        pass

    @abstractmethod
    def info(self, message: str, **kwargs: Any) -> None:
        pass

    @abstractmethod
    def warning(self, message: str, **kwargs: Any) -> None:
        pass

    @abstractmethod
    def error(self, message: str, **kwargs: Any) -> None:
        pass
    
    @abstractmethod
    def exception(self, message: str, exc_info: Optional[Exception] = None, **kwargs: Any) -> None:
        pass

    def with_context(self, **context: Any) -> 'Logger':
        """Возвращает новый логер в добавленным контекстом"""
        return ContextLogger(self, context)

class ContextLogger(Logger):
    """Логгер с добавленным контекстом"""
    
    def __init__(self, inner_logger: Logger, context: Dict[str, Any]):
        self.inner_logger = inner_logger
        self.context = context
    
    def debug(self, message: str, **kwargs: Any) -> None:
        self.inner_logger.debug(message, **{**self.context, **kwargs})
    
    def info(self, message: str, **kwargs: Any) -> None:
        self.inner_logger.info(message, **{**self.context, **kwargs})
    
    def warning(self, message: str, **kwargs: Any) -> None:
        self.inner_logger.warning(message, **{**self.context, **kwargs})
    
    def error(self, message: str, **kwargs: Any) -> None:
        self.inner_logger.error(message, **{**self.context, **kwargs})
    
    def exception(self, message: str, exc_info: Optional[Exception] = None, **kwargs: Any) -> None:
        self.inner_logger.exception(message, exc_info, **{**self.context, **kwargs})