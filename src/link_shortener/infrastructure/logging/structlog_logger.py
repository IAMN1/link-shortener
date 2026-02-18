from typing import Any, Optional

import structlog

from link_shortener.application import Logger


class StructLogger(Logger):
    """
    Обертка над structlog.
    """

    def __init__(self, name: Optional[str] = None):
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
