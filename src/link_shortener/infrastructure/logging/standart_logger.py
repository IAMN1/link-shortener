import logging
from typing import Any, Optional
from link_shortener.application import Logger


class StandartLogger(Logger):
    """Adapter for standard logging module."""

    def __init__(self, name: str = __name__, level: int = logging.INFO):
        self._logger = logging.getLogger(name)
        self._logger.setLevel(level)

        if not self._logger.handlers:
            self._logger.addHandler(logging.NullHandler())
    

    def debug(self, message: str, **kwargs: Any) -> None:
        if kwargs:
            self._logger.debug(f"{message} - %s", kwargs)
        else:
            self._logger.debug(message)
    
    def info(self, message: str, **kwargs: Any) -> None:
        if kwargs:
            self._logger.info(f"{message} - %s", kwargs)
        else:
            self._logger.info(message)
    
    def warning(self, message: str, **kwargs: Any) -> None:
        if kwargs:
            self._logger.warning(f"{message} - %s", kwargs)
        else:
            self._logger.warning(message)
    
    def error(self, message: str, **kwargs: Any) -> None:
        if kwargs:
            self._logger.error(f"{message} - %s", kwargs)
        else:
            self._logger.error(message)
    
    def exception(
        self, message: str, exc_info: Optional[Exception] = None, **kwargs: Any
    ) -> None:
        self._logger.exception(message, exc_info=exc_info, extra=kwargs)
