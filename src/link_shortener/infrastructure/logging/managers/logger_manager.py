import sys
from typing import Dict, List, Optional, Tuple

from link_shortener.application import Logger
from link_shortener.infrastructure.failover.failover_service import FailoverService
from link_shortener.infrastructure.logging.handlers.logger.null_logger import NullLogger
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
                return logger.is_healthy()

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
    Proxy that forwards logging calls to the FailoverService.

    It adds the module name as a bound field and supports additional
    `bind` operations. This allows contextual logging across multiple
    logger instances.
    """

    def __init__(self, service: FailoverService, module_name: str, bound_fields: Optional[Dict]= None):
        """
        Initialize the proxy.

        Args:
            service: The `FailoverService` that holds the actual loggers.
            module_name: Name of the module requesting the logger.
            bound_fields: Initial bound fields.
        """
        self._service = service
        self._module_name = module_name
        self._bound_fields = bound_fields if bound_fields else {}

    def bind(self, **kwargs) -> "FailoverLoggerProxy":
        """
        Return a new proxy with additional bound fields.

        Args:
            **kwargs: Fields to bind.

        Returns:
            A new `FailoverLoggerProxy` instance with merged bound fields.
        """
        new_bound = {**self._bound_fields, **kwargs}
        return FailoverLoggerProxy(self._service, self._module_name, new_bound)

    def _call(self, method_name: str, message: str, **kwargs):
        """
        Internal method to forward a logging call.

        Args:
            method_name: Name of the log method (debug, info, etc.).
            message: Log message.
            **kwargs: Additional structured data
        """
        all_kwargs = {**self._bound_fields, **kwargs}
        all_kwargs["module"] = self._module_name
        return self._service.execute(method_name, message, **all_kwargs)

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
    Simple wrapper for a single logger (when failover is disabled).

    It adds the module name to every log call as the "module" field.
    Supports `bind` to attach additional context.
    """

    def __init__(self, logger: Logger, module_name: str, bound_fields: Optional[Dict] = None):
        """
        Initialize the module logger.

        Args:
            logger: The underlying logger instance.
            module_name: Name of the module requesting the logger.
            bound_fields: Initial bound fields.
        """
        self._logger = logger
        self._module_name = module_name
        self._bound_fields = bound_fields if bound_fields else {}

    def bind(self, **kwargs) -> '_ModuleLogger':
        """
        Return a new module logger with additional bound fields.

        Args:
            **kwargs: Fields to bind.

        Returns:
            A new `_ModuleLogger` instance with merged bound fields.
        """
        new_bound = {**self._bound_fields, **kwargs}
        return _ModuleLogger(self._logger, self._module_name, new_bound)

    def _log(self, level: str, message: str, **kwargs):
        """
        Internal method to perform the actual logging.

        Args:
            level: Log level (debug, info, warning, error, exception).
            message: Log message.
            **kwargs: Additional structured data.
        """
        all_kwargs = {**self._bound_fields, **kwargs}
        all_kwargs["module"] = self._module_name
        getattr(self._logger, level)(message, **all_kwargs)

    def debug(self, message: str, **kwargs):
        self._log("debug", message, **kwargs)

    def info(self, message: str, **kwargs):
        self._log("info", message, **kwargs)

    def warning(self, message: str, **kwargs):
        self._log("warning", message, **kwargs)

    def error(self, message: str, **kwargs):
        self._log("error", message, **kwargs)

    def exception(self, message: str, exc_info=None, **kwargs):
        kwargs["exc_info"] = exc_info
        self._log("exception", message, **kwargs)
