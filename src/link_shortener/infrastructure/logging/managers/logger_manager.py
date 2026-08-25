"""
Logger manager: creates and manages application loggers with failover.

The ``LoggerManager`` builds an ordered list of logger implementations and
optionally wraps them in a ``FailoverService``. The order follows
``LOGGER_TYPE``: "auto" and "structlog" give structlog then standard,
"standard" gives standard then structlog, and "null" gives one null logger
and no failover at all. Null is never put *behind* the two real ones -- a
call both refuse is refused outright rather than quietly swallowed.
Module-specific loggers are created via proxies that add ``module`` context.
"""


from typing import Dict, List, Optional, Tuple

from link_shortener.application import Logger
from link_shortener.infrastructure.failover.failover_service import FailoverService
from link_shortener.infrastructure.failover.minimal_logger import MinimalLogger
from link_shortener.infrastructure.logging.handlers.logger.null_logger import NullLogger
from link_shortener.infrastructure.logging.handlers.logger.standard import StandardLogger
from link_shortener.infrastructure.logging.handlers.logger.structlog import StructLogger


class LoggerManager:
    """
    Manages logger instances with failover support.

    This class is not a singleton – its lifecycle is controlled by the DI
    container. It provides loggers for different modules, each potentially
    wrapped to add module context.
    """

    def __init__(
        self,
        logger_type: str,
        failover_check_interval: float = 30.0,
        logger: Optional[MinimalLogger] = None
    ):
        """
        Initialize the logger manager.

        Args:
            logger_type: Type of logger to use. One of:
                ``"auto"``, ``"structlog"``, ``"standard"``, ``"null"``.
            failover_check_interval: Seconds between background health checks.
            logger: Logger for internal messages; defaults to ``MinimalLogger``.
        """
        self._failover_check_interval = failover_check_interval
        self.logger = logger if logger is not None else MinimalLogger()
        self._failover_service: Optional[FailoverService] = None
        self._active_logger: Optional[Logger] = None
        # The name the implementation was built under, kept rather than
        # worked out again later: see ``get_active_logger_name``.
        self._active_logger_name = "unknown"
        self._loggers_cache: Dict[str, Logger] = {}
        self._init_failover_service(logger_type)

    def _init_failover_service(self, logger_type: str):
        """
        Build the ordered list of logger implementations based on the requested
        type and set up failover if multiple implementations are available.

        Args:
            logger_type: The configured logger type.
        """
        # Case and surrounding blanks come off first: the comparisons below
        # are against exact strings, so ``NULL``, ``Null`` and ``"null "``
        # would miss the ``null`` branch and fall through to the default --
        # the full chain, which is the opposite of what was asked for.
        # Anything still unrecognised falls through to the default.
        logger_type = (logger_type or "").strip().lower()

        # Determine priority order
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

        # Declared by the port both branches produce: the two implementations
        # are unrelated classes, and a variable typed from whichever came
        # first rejects the other.
        logger: Logger

        for type_ in order:
            if type_ == "structlog":
                try:
                    logger = StructLogger(name="global")
                    loggers.append((logger, "structlog"))
                except Exception as e:
                    self.logger.warning(
                        f"Failed to initialize StructLogger: {e}"
                    )
            elif type_ == "standard":
                try:
                    logger = StandardLogger(name="global")
                    loggers.append((logger, "standard"))
                except Exception as e:
                    self.logger.warning(
                        f"Failed to initialize StandardLogger: {e}"
                    )
            elif type_ == "null":
                loggers.append((NullLogger(), "null"))

        # Ensure at least one logger is available
        if not loggers:
            loggers.append((NullLogger(), "null"))

        # Single logger: no failover
        if len(loggers) == 1:
            self._failover_service = None
            self._active_logger, self._active_logger_name = loggers[0]
        else:
            # Health checker using is_healthy
            def health_check(logger: Logger) -> bool:
                return logger.is_healthy()

            self._failover_service = FailoverService(
                services=loggers,
                check_interval=self._failover_check_interval,
                health_checker=health_check,
                upgrade_cooldown=300,
                logger=self.logger,
            )

    @property
    def _single_logger(self) -> Logger:
        """Return the logger built when no failover was needed.

        The attribute holds ``None`` until ``_init_failover_service`` picks
        an implementation, and stays ``None`` when several were built and
        the failover service owns them instead.

        Returns:
            The one active implementation.

        Raises:
            RuntimeError: If the manager holds no logger, which means its
                initialisation did not finish.
        """
        if self._active_logger is None:
            raise RuntimeError("LoggerManager has no logger (initialisation failed)")
        return self._active_logger

    def get_logger(self, module_name: str) -> Logger:
        """
        Return a logger for the given module name.

        If a proxy for this module already exists, returns it from cache.
        Otherwise creates a new wrapper that delegates calls through the
        failover service (or directly to the active logger).

        Args:
            module_name: Name of the module requesting the logger.

        Returns:
            A ``Logger`` instance.
        """
        if module_name in self._loggers_cache:
            return self._loggers_cache[module_name]

        logger: Logger
        if self._failover_service is None:
            logger = _ModuleLogger(self._single_logger, module_name)
        else:
            logger = FailoverLoggerProxy(self._failover_service, module_name)

        self._loggers_cache[module_name] = logger
        return logger

    def get_active_logger_name(self) -> str:
        """
        Return the name of the currently active logger implementation.

        The name the implementation was built under, in both branches. It
        was worked out again here, by ``isinstance`` over the classes --
        a second answer to a question the list of implementations had
        already answered, and one that could disagree with it. It is the
        same string either way now, so a chain reports itself the same
        whether or not failover was built for it.

        Returns:
            One of ``"structlog"``, ``"standard"``, ``"null"``, or
            ``"unknown"`` where nothing was built.
        """
        if self._failover_service:
            return self._failover_service.get_current_service_name()
        return self._active_logger_name

    def counters(self) -> Tuple[int, int, int]:
        """
        Report how much this chain has lost and how often it checked badly.

        All three numbers existed and nothing read them, so "the log
        stopped being written" looked exactly like "everything is fine"
        from every surface an operator has. Without failover there is
        nothing to count: one implementation cannot fail over, and a call
        it refuses raises at the caller rather than being dropped here.

        Returns:
            Dropped calls, failed health-check rounds and lost failover
            log lines, in that order.
        """
        if self._failover_service is None:
            return 0, 0, 0

        return (
            self._failover_service.dropped_calls,
            self._failover_service.failed_checks,
            self._failover_service.lost_log_lines,
        )

    def shutdown(self) -> bool:
        """
        Stop the background failover checker if it exists.

        Returns:
            True if there was nothing to stop or it stopped, False if the
            checker was still running when the wait ran out. The DI
            lifecycle that calls this discards the answer today; the
            failover service says so in its own log either way.
        """
        if self._failover_service:
            return self._failover_service.shutdown()
        return True


class FailoverLoggerProxy(Logger):
    """
    Proxy that forwards logging calls to the ``FailoverService``.

    It adds the module name as a bound field and supports additional
    ``bind`` operations. This allows contextual logging across multiple
    logger instances.
    """

    def __init__(
        self,
        service: FailoverService,
        module_name: str,
        bound_fields: Optional[Dict] = None
    ):
        """
        Initialize the proxy.

        Args:
            service: The ``FailoverService`` that holds the actual loggers.
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
            A new ``FailoverLoggerProxy`` instance with merged bound fields.
        """
        new_bound = {**self._bound_fields, **kwargs}
        return FailoverLoggerProxy(self._service, self._module_name, new_bound)

    def _call(self, method_name: str, message: str, **kwargs):
        """
        Internal method to forward a logging call to the failover service.

        Args:
            method_name: Name of the log method (e.g. ``"info"``).
            message: The log message.
            **kwargs: Additional structured data.

        Returns:
            Whatever the active logger answered -- ``None`` for the log
            methods, which return nothing -- or ``ALL_SERVICES_FAILED``
            when no logger accepted the line. The level methods below
            discard it; nothing else calls this.
        """
        all_kwargs = {**self._bound_fields, **kwargs}
        # A bound ``module`` wins over the name this proxy was built with;
        # one passed on the call does not, which is the distinction the
        # test beside this one is about. Where a line came from is a
        # property of the writer, so a writer may state it once by binding
        # it -- and a single line may not, or lines start attributing
        # themselves to whatever the call felt like naming.
        #
        # The name this proxy carries is the one the logger was *fetched*
        # under, and the fetching is done by the DI container: every record
        # an application-layer use case wrote was therefore filed under
        # ``link_shortener.infrastructure.di.container``, so the one field
        # saying where a record came from named the wiring rather than the
        # work. ``BaseUseCase._get_logger`` binds the real one.
        all_kwargs["module"] = self._bound_fields.get(
            "module", self._module_name
        )
        return self._service.execute(method_name, message, **all_kwargs)

    def debug(self, message: str, **kwargs):
        """Log a debug message."""
        self._call("debug", message, **kwargs)

    def info(self, message: str, **kwargs):
        """Log an informational message."""
        self._call("info", message, **kwargs)

    def warning(self, message: str, **kwargs):
        """Log a warning message."""
        self._call("warning", message, **kwargs)

    def error(self, message: str, **kwargs):
        """Log an error message."""
        self._call("error", message, **kwargs)

    def exception(self, message: str, exc_info=True, **kwargs):
        """Log an exception with traceback."""
        kwargs["exc_info"] = exc_info
        self._call("exception", message, **kwargs)

    def is_healthy(self) -> bool:
        """Check health through the failover service."""
        result = self._service.execute("is_healthy")
        return result is True


class _ModuleLogger(Logger):
    """
    Simple wrapper for a single logger when failover is disabled.

    It adds the module name as the ``"module"`` field on every log call
    and supports ``bind`` for additional context.

    This is an internal helper; its lifecycle is managed by ``LoggerManager``.
    """

    def __init__(
        self,
        logger: Logger,
        module_name: str,
        bound_fields: Optional[Dict] = None
    ):
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

    def bind(self, **kwargs) -> "_ModuleLogger":
        """
        Return a new module logger with additional bound fields.

        Args:
            **kwargs: Fields to bind.

        Returns:
            A new ``_ModuleLogger`` instance with merged bound fields.
        """
        new_bound = {**self._bound_fields, **kwargs}
        return _ModuleLogger(self._logger, self._module_name, new_bound)

    def _log(self, level: str, message: str, **kwargs):
        """
        Perform the actual logging by calling the underlying logger's method.

        Args:
            level: Log level (e.g. ``"info"``).
            message: The log message.
            **kwargs: Additional structured data.
        """
        all_kwargs = {**self._bound_fields, **kwargs}
        # A bound name wins, a called one does not: see the reasoning in
        # ``FailoverLoggerProxy._call``.
        all_kwargs["module"] = self._bound_fields.get(
            "module", self._module_name
        )
        getattr(self._logger, level)(message, **all_kwargs)

    def debug(self, message: str, **kwargs):
        self._log("debug", message, **kwargs)

    def info(self, message: str, **kwargs):
        self._log("info", message, **kwargs)

    def warning(self, message: str, **kwargs):
        self._log("warning", message, **kwargs)

    def error(self, message: str, **kwargs):
        self._log("error", message, **kwargs)

    def exception(self, message: str, exc_info=True, **kwargs):
        kwargs["exc_info"] = exc_info
        self._log("exception", message, **kwargs)

    def is_healthy(self) -> bool:
        """Delegate health check to the underlying logger."""
        return self._logger.is_healthy()
