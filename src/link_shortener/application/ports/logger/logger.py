from abc import ABC, abstractmethod
from typing import Any


class Logger(ABC):
    """
    Abstract interface for application logging.

    This allows the application core to remain decoupled
    from concrete logging implementations.
    """

    def bind(self, **kwargs) -> "Logger":
        """
        Return a logger that carries these fields into every later call.

        Useful for context that belongs to a whole request -- its id, the
        caller's address -- without passing them explicitly each time.

        Implementations that can carry fields return a new instance and
        leave this one alone. The default here returns ``self``, which is
        the honest answer for a logger that keeps nothing: ``NullLogger``
        discards the fields either way, and handing back a copy of a sink
        would only suggest otherwise.

        Args:
            **kwargs: Key-value pairs to bind to the logger.

        Returns:
            A logger carrying the fields -- a new instance where that means
            anything, and ``self`` where it does not.
        """
        return self

    @abstractmethod
    def debug(self, message: str, **kwargs: Any) -> None:
        """
        Log a debug message with optional keyword arguments as structured data.
        """
        ...

    @abstractmethod
    def info(self, message: str, **kwargs: Any) -> None:
        """Log an info message with optional structured data."""
        ...

    @abstractmethod
    def warning(self, message: str, **kwargs: Any) -> None:
        """Log a warning message with optional structured data."""
        ...

    @abstractmethod
    def error(self, message: str, **kwargs: Any) -> None:
        """Log an error message with optional structured data."""
        ...

    @abstractmethod
    def exception(
        self, message: str, exc_info: Any = True, **kwargs: Any
    ) -> None:
        """
        Log an exception with traceback.

        Args:
            message: Log message.
            exc_info: What to render a traceback from. ``True`` -- the
                default -- takes the exception being handled, which is what
                ``logging.Logger.exception`` and ``structlog.exception``
                both do. An exception instance is rendered instead.
                ``None`` means no traceback at all: the renderer skips a
                falsy value, so the line comes out without one. The default
                used to be ``None``, which made a bare ``log.exception(...)``
                print a line that looked like a traceback and had none.
            **kwargs: Additional structured data.
        """
        ...

    @abstractmethod
    def is_healthy(self) -> bool:
        """Check if logger can write messages right now."""
        ...
