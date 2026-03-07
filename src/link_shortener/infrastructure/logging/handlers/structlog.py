from typing import Any, Optional

import structlog

from link_shortener.application import Logger


class StructLogger(Logger):
    """
    Adapter for structlog, implementing the Logger interface.
    """

    def __init__(self, name: Optional[str] = None):
        """
        Initialize the structlog logger.

        Args:
            name: Logger name (defaults to __name__ of caller if None).
        """
        self.logger = structlog.get_logger(name or __name__)

    def debug(self, message: str, **kwargs: Any) -> None:
        self.logger.debug(message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        self.logger.info(message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        self.logger.warning(message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        self.logger.error(message, **kwargs)

    def exception(
        self, message: str, exc_info=Optional[Exception], **kwargs: Any
    ) -> None:
        self.logger.exception(message, exc_info=exc_info, **kwargs)
