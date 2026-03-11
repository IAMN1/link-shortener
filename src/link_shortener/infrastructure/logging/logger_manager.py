import sys
from typing import Dict, List, Optional, Tuple

from link_shortener.application import Logger
from link_shortener.application.ports.logger.null_logger import NullLogger
from link_shortener.infrastructure.failover.base import FailoverService
from link_shortener.infrastructure.logging.handlers.logger.standard import StandardLogger
from link_shortener.infrastructure.logging.handlers.logger.structlog import StructLogger


class LoggerManager:
    """
    Manages logger instances with failover support.

    This class is not a singleton – its lifecycle is controlled by the DI container.
    It provides loggers for different modules, each potentially wrapped to add module context.
    """


    def __init__(self, logger_type: str, failover_check_interval: float = 30.0):
        """
        Initialize the logger manager.

        Args:
            logger_type: Type of logger ('auto', 'structlog', 'standard', 'null').
            failover_check_interval: Seconds between background health checks.
        """
        self._failover_check_interval = failover_check_interval
        self._failover_service: Optional[FailoverService] = None
        self._active_logger: Optional[Logger] = None
        self._loggers_cache: Dict[str, Logger] = {}
        self._init_failover_service(logger_type)

    def _init_failover_service(self, logger_type: str):
        """Build the ordered list of logger implementations based on type."""

        if logger_type == "auto":
            order = ["structlog", "standard"]
        elif logger_type == "structlog":
            order = ["structlog", "standard"]
        elif logger_type == "standard":
            order = ["standard", "structlog"]
        elif logger_type == "null":
            order = ["null"]
        else:
            order = ["structlog", "standard"]

        loggers: List[Tuple[Logger, str]] = []

        for type_ in order:
            if type_ == "structlog":

                try:
                    logger = StructLogger(name="global")
                    loggers.append((logger, "structlog"))
                except Exception as e:
                    print(
                        f"WARNING: Failed to initialize StructLogger: {e}",
                        file=sys.stderr
                    )

            elif type_ == "standard":

                try:
                    logger = StandardLogger(name="global")
                    loggers.append((logger, "standard"))
                except Exception as e:
                    print(
                        f"WARNING: Failed to initialize StandardLogger: {e}",
                        file=sys.stderr
                    )

            elif type_ == "null":
                loggers.append((NullLogger(), "null"))

        if not loggers:
            loggers.append((NullLogger(), "null"))

        if len(loggers) == 1:  # only NullLogger
            self._failover_service = None
            self._active_logger = loggers[0][0]
        else:
            # Define health check function
            def health_check(logger: Logger) -> bool:
                try:
                    logger.debug("Health check from FailoverService")
                    return True
                except Exception:
                    return False

            self._failover_service = FailoverService(
                services=loggers,
                check_interval=self._failover_check_interval,
                health_checker=health_check,
            )

    def get_logger(self, module_name: str) -> Logger:
        """
        Return a logger for the given module name.

        If a proxy for this module already exists, returns it from cache.
        Otherwise creates a new FailoverLoggerProxy that will delegate calls
        to the failover service, passing the module name as additional context.

        Args:
            module_name: Name of the module requesting the logger.

        Returns:
            Logger instance.
        """
        if module_name in self._loggers_cache:
            return self._loggers_cache[module_name]

        if self._failover_service is None:
            # No failover, just return the single active logger (but with module context)
            logger = _ModuleLogger(self._active_logger, module_name)
        else:
            logger = FailoverLoggerProxy(self._failover_service, module_name)

        self._loggers_cache[module_name] = logger
        return logger

    def get_active_logger_name(self) -> str:
        """Return the name of the currently active logger."""
        if self._failover_service:
            return self._failover_service.get_current_service_name()
        elif self._active_logger:
            # Determine by type
            if isinstance(self._active_logger, StructLogger):
                return "structlog"
            elif isinstance(self._active_logger, StandardLogger):
                return "standard"
            else:
                return "null"
        return "unknown"
    
    def shutdown(self):
        """Stop the background failover checker if it exists."""
        if self._failover_service:
            self._failover_service.shutdown()


class FailoverLoggerProxy(Logger):
    """
    Proxy that forwards logging calls to the FailoverService,
    adding the module name to the keyword arguments.
    """

    def __init__(self, service: FailoverService, module_name: str):
        self._service = service
        self._module_name = module_name

    def _call(self, method_name: str, message: str, **kwargs):
        kwargs["module"] = self._module_name
        return self._service.execute(method_name, message, **kwargs)

    def debug(self, message: str, **kwargs):
        self._call("debug", message, **kwargs)

    def info(self, message: str, **kwargs):
        self._call("info", message, **kwargs)

    def warning(self, message: str, **kwargs):
        self._call("warning", message, **kwargs)

    def error(self, message: str, **kwargs):
        self._call("error", message, **kwargs)

    def exception(self, message: str, exc_info=None, **kwargs):
        kwargs["exc_info"] = exc_info
        self._call("exception", message, **kwargs)


class _ModuleLogger(Logger):
    """
    Simple wrapper for a single logger (when failover is disabled)
    that adds module name to kwargs.
    """

    def __init__(self, logger: Logger, module_name: str):
        self._logger = logger
        self._module_name = module_name

    def debug(self, message: str, **kwargs):
        kwargs["module"] = self._module_name
        self._logger.debug(message, **kwargs)

    def info(self, message: str, **kwargs):
        kwargs["module"] = self._module_name
        self._logger.info(message, **kwargs)

    def warning(self, message: str, **kwargs):
        kwargs["module"] = self._module_name
        self._logger.warning(message, **kwargs)

    def error(self, message: str, **kwargs):
        kwargs["module"] = self._module_name
        self._logger.error(message, **kwargs)

    def exception(self, message: str, exc_info=None, **kwargs):
        kwargs["module"] = self._module_name
        kwargs["exc_info"] = exc_info
        self._logger.exception(message, **kwargs)
