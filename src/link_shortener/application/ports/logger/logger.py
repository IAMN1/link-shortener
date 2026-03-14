from abc import ABC, abstractmethod
from typing import Any, Optional


class Logger(ABC):
    """
    Abstract interface for application logging.

    This allows the application core to remain decoupled
    from concrete logging implementations.
    """

    def bind(self, **kwargs) -> "Logger":
        """
        Return a new logger instance with additional bound fields.

        Bound fields are included in every subsequent log call.
        This is useful for adding contextual information like request ID,
        user IP, etc., without passing them explicitly each time.

        Args:
            **kwargs: Key-value pairs to bind to the logger.

        Returns:
            A new Logger instance with the bound fields.
        """
        return self

    @abstractmethod
    def debug(self, message: str, **kwargs: Any) -> None:
        """
        Log a debug message with optional keyword arguments as structured data.
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
            message: Log message.
            exc_info: Exception to log (if None, current exception is captured). Optional.
            **kwargs: Additional structured data.
        """
        pass

