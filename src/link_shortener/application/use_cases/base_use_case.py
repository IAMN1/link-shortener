from abc import ABC
from dataclasses import asdict

from link_shortener.application.context import RequestContext
from link_shortener.application import Logger


class BaseUseCase(ABC):
    """
    Base class for all use cases.

    Provides a helper method `_get_logger` that binds the request context
    (and any extra fields) to the given logger, enabling structured logging
    with contextual information automatically included.
    """

    def _get_logger(self, logger: Logger, context: RequestContext, **extra) -> Logger:
        """
        Return a logger with bound fields from the request context and extra data.

        Args:
            logger: The original logger instance.
            context: RequestContext containing request metadata (IP, user agent, request ID, etc.).
            **extra: Additional key-value pairs to bind (usecase specific).

        Returns:
            Logger: A logger with the bound fields (may be a new instance or the same,
                depending on the logger implementation).
        """
        # asdict преобразует все поля dataclass в словарь
        return logger.bind(**asdict(context), **extra)