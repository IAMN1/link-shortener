from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class Logger(ABC):
    """
    Abstract interface for application logging.

    This allows the application core to remain decoupled 
        from concrete logging implementations.
    """

    @abstractmethod
    def debug(self, message: str, **kwargs: Any) -> None:
        """
        Log a debug message with optional 
            keyword arguments as structured data.
        """
        pass

    @abstractmethod
    def info(self, message: str, **kwargs: Any) -> None:
        """Log an info message with optional structured data."""
        pass

    @abstractmethod
    def warning(self, message: str, **kwargs: Any) -> None:
        """Log a warning message with optional structured data."""
        pass

    @abstractmethod
    def error(self, message: str, **kwargs: Any) -> None:
        """Log an error message with optional structured data."""
        pass

    @abstractmethod
    def exception(
        self, message: str, exc_info: Optional[Exception] = None, **kwargs: Any
    ) -> None:
        """
        Log an exception with traceback.

        Args:
            message (str): Log message.
            exc_info (Optional[Exception], optional): Exception to log 
                (if None, current exception is captured). Defaults to None.
            **kwargs: Additional structured data.
        """
        pass

    def with_context(self, **context: Any) -> "Logger":
        """
        Return a new logger that includes the given context 
            in all subsequent log calls.

        Args:
            **context: Key-value pairs to add to log entries.

        Returns:
            A logger instance with bound context.
        """
        return ContextLogger(self, context)


class ContextLogger(Logger):
    """
    Logger decorator that adds static context to every log message.

    Used internally by Logger.with_context().
    """

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

    def exception(
        self, message: str, exc_info: Optional[Exception] = None, **kwargs: Any
    ) -> None:
        self.inner_logger.exception(message, exc_info, **{**self.context, **kwargs})
