from abc import ABC, abstractmethod
from typing import Any, Optional


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

