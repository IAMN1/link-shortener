from typing import List, Tuple
from link_shortener.application import Logger
from link_shortener.infrastructure.failover.base import FailoverService


class FailoverLogger(Logger):
    """
    Logger that delegates to a FailoverService managing multiple underlying loggers.
    Includes background health checks to upgrade to a higher-priority logger
    when it becomes available.
    """

    def __init__(
        self, loggers: List[Tuple[Logger, str]], check_interval: float = 30.0
    ):
        """Initialize the failover logger.

        Args:
            loggers: List of (logger_instance, logger_name) in priority order.
            check_interval: Seconds between background health checks.
        """
        def _health_check(logger: Logger) -> bool:
            try:
                logger.debug("FailoverLogger health check")
                return True
            except Exception:
                return False

        self._service = FailoverService[Logger](
            services=loggers,
            check_interval=check_interval,
            health_checker=_health_check,
        )

    def get_current_logger_name(self) -> str:
        """"""
        return self._service.get_current_serivice_name()


    def debug(self, message: str, **kwargs):
        self._service.execute("debug", message, **kwargs)

    def info(self, message: str, **kwargs):
        self._service.execute("info", message, **kwargs)

    def warning(self, message: str, **kwargs):
        self._service.execute("warning", message, **kwargs)

    def error(self, message: str, **kwargs):
        self._service.execute("error", message, **kwargs)

    def exception(self, message: str, exc_info=None, **kwargs):
        self._service.execute("exception", message, exc_info=exc_info, **kwargs)