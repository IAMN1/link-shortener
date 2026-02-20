from typing import Any, Optional
from link_shortener.application import Logger


class NullLogger(Logger):
    """
    Null-object logger that discards all messages.
    """

    def debug(self, message: str, **kwargs: Any) -> None:
        pass

    def info(self, message: str, **kwargs: Any) -> None:
        pass

    def warning(self, message: str, **kwargs: Any) -> None:
        pass

    def error(self, message: str, **kwargs: Any) -> None:
        pass

    def exception(
        self, message: str, exc_info: Optional[Exception] = None, **kwargs: Any
    ) -> None:
        pass