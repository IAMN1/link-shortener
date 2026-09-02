"""
Audit manager: creates and manages audit loggers with failover support.

The ``AuditManager`` builds an ordered list of audit logger implementations
and optionally wraps them in a ``FailoverService``. The order follows
``AUDIT_TYPE`` exactly as ``LOGGER_TYPE`` drives the logger chain, and null
is never placed behind the real implementations.
When failover is active, a proxy is returned that automatically switches
to a healthy fallback logger if the primary one fails.
"""


from typing import List, Optional, Tuple

from link_shortener.application import AuditEvent, AuditLogger
from link_shortener.infrastructure.failover.failover_service import (
    CheckOutcome, FailoverService,
)
from link_shortener.infrastructure.failover.minimal_logger import MinimalLogger
from link_shortener.infrastructure.logging.handlers.audit.null_audit import NullAuditLogger
from link_shortener.infrastructure.logging.handlers.audit.standard import StandardAuditLogger
from link_shortener.infrastructure.logging.handlers.audit.structlog import StructlogAuditLogger


class AuditManager:
    """
    Manages audit logger instances with optional failover support.

    Based on the configured ``audit_type``, this class creates a list of
    available audit logger implementations, in the order AUDIT_TYPE asks for
    in priority order. If multiple implementations are available, a
    ``FailoverService`` is used to automatically switch to a fallback
    when the primary fails.

    Lifecycle is controlled by the DI container.
    """

    def __init__(
        self,
        audit_type: str,
        failover_check_interval: float = 30.0,
        logger: Optional[MinimalLogger] = None
    ):
        """
        Initialize the audit manager.

        Args:
            audit_type: Type of audit logger to use. One of:
                ``"auto"``, ``"structlog"``, ``"standard"``, ``"null"``.
            failover_check_interval: Seconds between background health checks
                (ignored if only one implementation is available).
            logger: Logger for internal diagnostics. Defaults to ``MinimalLogger``.
        """
        self._failover_check_interval = failover_check_interval
        self.logger = logger if logger is not None else MinimalLogger()
        self._failover_service: Optional[FailoverService] = None
        self._active_audit_logger: Optional[AuditLogger] = None
        # The name the implementation was built under, kept rather than
        # read off its class later: see ``active_name``.
        self._active_audit_name = "unknown"
        self._init_failover_service(audit_type)

    def _init_failover_service(self, audit_type: str):
        """
        Build the ordered list of audit logger implementations based on the
        requested type and wrap them in a ``FailoverService`` when appropriate.

        Args:
            audit_type: The configured audit type.
        """
        # Case and surrounding blanks are taken off first, for the reason
        # given in ``LoggerManager``: ``AUDIT_TYPE=NULL`` missed the
        # ``null`` branch and fell through to the default, so auditing
        # stayed fully on where an operator had switched it off.
        audit_type = (audit_type or "").strip().lower()

        # Determine priority order
        if audit_type == "auto":
            order = ["structlog", "standard"]
        elif audit_type == "structlog":
            order = ["structlog", "standard"]
        elif audit_type == "standard":
            order = ["standard", "structlog"]
        elif audit_type == "null":
            order = ["null"]
        else:
            order = ["structlog", "standard"]

        audit_loggers: List[Tuple[AuditLogger, str]] = []

        for type_ in order:
            if type_ == "structlog":
                try:
                    struct_audit = StructlogAuditLogger()
                    audit_loggers.append((struct_audit, "structlog_audit"))
                except Exception as e:
                    self.logger.warning(
                        f"Failed to initialize StructlogAuditLogger: {e}"
                    )
            elif type_ == "standard":
                try:
                    std_audit = StandardAuditLogger()
                    audit_loggers.append((std_audit, "standard_audit"))
                except Exception as e:
                    self.logger.warning(
                        f"Failed to initialize StandardAuditLogger: {e}"
                    )
            elif type_ == "null":
                audit_loggers.append((NullAuditLogger(), "null_audit"))

        # Ensure at least one logger is available
        if not audit_loggers:
            audit_loggers.append((NullAuditLogger(), "null_audit"))

        # If only one logger (Null), no failover is needed
        if len(audit_loggers) == 1:
            self._failover_service = None
            self._active_audit_logger, self._active_audit_name = audit_loggers[0]
        else:
            # Use health checker based on is_healthy method
            def health_check(audit: AuditLogger) -> bool:
                return audit.is_healthy()

            self._failover_service = FailoverService(
                services=audit_loggers,
                check_interval=self._failover_check_interval,
                health_checker=health_check,
                upgrade_cooldown=300,
                logger=self.logger
            )

    @property
    def _single_audit_logger(self) -> AuditLogger:
        """Return the audit logger built when no failover was needed.

        The attribute holds ``None`` until ``_init_failover_service`` picks
        an implementation, and stays ``None`` when several were built and
        the failover service owns them instead.

        Returns:
            The one active implementation.

        Raises:
            RuntimeError: If the manager holds no audit logger, which means
                its initialisation did not finish.
        """
        if self._active_audit_logger is None:
            raise RuntimeError("AuditManager has no audit logger (initialisation failed)")
        return self._active_audit_logger

    def get_audit_logger(self) -> AuditLogger:
        """
        Return an audit logger.

        If failover is configured, a fresh ``FailoverAuditLoggerProxy`` over
        the one ``FailoverService``; otherwise the single active logger. The
        proxy is built per call rather than cached, as
        ``LoggerManager.get_logger`` caches its own: this one holds nothing
        but bound fields and the service, and callers bind on it anyway,
        which produces a new proxy every time regardless.

        Returns:
            An ``AuditLogger`` instance.
        """
        if self._failover_service is None:
            return self._single_audit_logger
        return FailoverAuditLoggerProxy(self._failover_service)

    def active_name(self) -> str:
        """
        Name the audit implementation currently doing the work.

        The name it was built under, in both branches. Without failover
        this answered ``type(...).__name__`` -- so the same chain called
        itself ``null_audit`` where failover happened to be built and
        ``NullAuditLogger`` where it was not, and ``/api/v1/admin/health``
        published a Python class name beside the journal chain's
        ``null``. One field, two vocabularies, decided by a wiring detail
        the reader cannot see.

        Returns:
            The failover service's current pick, or the single
            implementation's own name when no failover was built.
        """
        if self._failover_service is not None:
            return self._failover_service.get_current_service_name()

        return self._active_audit_name

    def counters(self) -> Tuple[int, int, int]:
        """
        Report how much this chain has lost and how often it checked badly.

        See ``LoggerManager.counters``: the same three numbers, for the
        audit chain, and unread by anything until now.

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

    def last_check(self) -> str:
        """
        What the last background round found the active audit logger to be.

        See ``LoggerManager.last_check``. Measured on the audit chain
        because that is where it was measured missing: with ``audit.log``
        replaced by a directory on a running application, the round said
        "structlog_audit reports itself unhealthy" eight times in ninety
        seconds and every counter beside it stayed at zero.

        Returns:
            One of ``CheckOutcome``'s values.
        """
        if self._failover_service is None:
            return CheckOutcome.NOT_RUN.value

        return self._failover_service.last_check.value

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


class FailoverAuditLoggerProxy(AuditLogger):
    """
    Proxy that forwards audit calls to the ``FailoverService``.

    It maintains its own ``_bound_fields`` to support ``bind`` operations.
    When a log method is called, it merges bound fields with the arguments
    and delegates to the service.
    """

    def __init__(
        self, service: FailoverService, bound_fields: Optional[dict] = None
    ):
        """
        Initialize the proxy.

        Args:
            service: The ``FailoverService`` that holds the actual loggers.
            bound_fields: Initial bound fields (e.g., request context).
        """
        self._service = service
        self._bound_fields = bound_fields or {}

    def bind(self, **kwargs) -> "FailoverAuditLoggerProxy":
        """
        Return a new proxy with additional bound fields.

        Args:
            **kwargs: Fields to bind.

        Returns:
            A new ``FailoverAuditLoggerProxy`` instance with merged bound fields.
        """
        return FailoverAuditLoggerProxy(
            self._service, {**self._bound_fields, **kwargs}
        )

    POSITIONAL_FIELDS = ("short_code", "original_url", "event")
    """Names this proxy passes positionally to the implementations.

    A bound field with one of these names would otherwise reach the same
    call as a keyword. Reproduced by binding one by hand:
    ``bind(short_code=...)`` gives ``TypeError: got multiple values for
    argument 'short_code'``, both implementations refuse the call,
    ``dropped_calls`` grows and the chain moves to the standby -- over a
    mistake in this proxy rather than anything wrong with the logger.

    No call site does it today: every caller of ``_get_audit_logger`` --
    there are two dozen -- passes only ``context``, and
    ``RequestContext.for_logging`` returns ``request_id``,
    ``remote_addr``, ``user_agent``, ``request_path``, ``request_method``
    and ``user_id``. The guard is for the caller that passes ``**extra``,
    which the signature invites.

    ``event`` is here for ``log_security_event`` and costs the link events
    nothing: it is not a field any of them writes, and it is not one a
    context could sensibly carry -- structlog spells the message itself
    ``event``, so a bound field of that name is already a collision with
    the record's own text rather than a piece of context.
    """

    def _context(self, **kwargs) -> dict:
        """
        Merge bound fields with call fields, dropping the collisions.

        The call already wins over a bound field of the same name, which is
        this proxy's rule everywhere; the event's own arguments are part of
        the call, so the same rule decides here. A bound ``short_code`` is
        therefore dropped rather than sent, because sending it cannot mean
        anything but "override the event with context", and that would put
        a different code in the audit trail than the one that was created.

        Dropped from the binding only. A field the *caller* passed under
        one of these names is theirs to record: on the three link events
        it cannot collide, since Python refuses two values for one
        parameter before this method is entered, and on
        ``log_security_event`` -- which passes only ``event``
        positionally -- ``short_code`` and ``original_url`` are ordinary
        fields. Dropping those took a value the caller asked to record out
        of the trail, and said nothing about it.

        Args:
            **kwargs: Fields supplied by the caller of the event method.

        Returns:
            The context to forward, with no bound name the event passes
            positionally.
        """
        merged = {**self._bound_fields, **kwargs}
        for name in self.POSITIONAL_FIELDS:
            if name not in kwargs:
                merged.pop(name, None)

        return merged

    def log_url_created(self, short_code: str, original_url: str, **kwargs) -> None:
        """
        Forward the URL creation event to the active audit logger via failover.

        Args:
            short_code: The generated short code.
            original_url: The original long URL.
            **kwargs: Additional context.
        """
        all_kwargs = self._context(**kwargs)
        self._service.execute(
            "log_url_created", short_code, original_url, **all_kwargs
        )

    def log_url_accessed(self, short_code: str, original_url: str, **kwargs) -> None:
        """
        Forward the URL access event to the active audit logger via failover.

        Args:
            short_code: The short code that was accessed.
            original_url: The original URL to which the user was redirected.
            **kwargs: Additional context.
        """
        all_kwargs = self._context(**kwargs)
        self._service.execute(
            "log_url_accessed", short_code, original_url, **all_kwargs
        )

    def log_url_deleted(self, short_code: str, original_url: str, **kwargs) -> None:
        """
        Forward the URL deletion event to the active audit logger via failover.

        Args:
            short_code: The short code of the deleted link.
            original_url: The original long URL that was shortened.
            **kwargs: Additional context.
        """
        all_kwargs = self._context(**kwargs)
        self._service.execute(
            "log_url_deleted", short_code, original_url, **all_kwargs
        )

    def log_security_event(self, event: AuditEvent, **fields) -> None:
        """
        Forward a security event to the active audit logger via failover.

        Args:
            event: Which event this is.
            **fields: The event's fields.
        """
        all_kwargs = self._context(**fields)
        self._service.execute("log_security_event", event, **all_kwargs)

    def is_healthy(self) -> bool:
        """
        Check the health of the audit logger through the failover service.

        Returns:
            ``True`` if the currently active audit logger is healthy.
        """
        result = self._service.execute("is_healthy")
        return result is True
