from abc import ABC

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.domain import (
    LinkNotFoundError, ShortCode, ValidationError
)


class BaseUseCase(ABC):
    """
    Base class for all use cases.

    Provides helper methods to obtain loggers and audit loggers with
    automatically bound request context (request_id, remote_addr, etc.).
    """

    @staticmethod
    def _code_to_look_up(short_code_str: str) -> ShortCode:
        """
        Read a short code that is about to be looked up.

        A code the format rules refuse is a code no link can carry, so the
        honest answer is that there is no such link -- the same answer as
        for a well-formed code nobody has taken. Reported as a validation
        failure instead, one condition produced three different statuses
        across the API: ``GET /nope`` answered 400 while ``GET /abcdefg``
        answered 404, and ``DELETE`` answered 404 for both because it
        happened to swallow the error. On the redirect route, which catches
        every unmatched path, 400 also means the service calls a
        non-existent page a bad request.

        Args:
            short_code_str: Code as it arrived from the caller.

        Returns:
            The validated code.

        Raises:
            LinkNotFoundError: If the string cannot be a short code.
        """
        try:
            return ShortCode(short_code_str)
        except ValidationError:
            raise LinkNotFoundError(short_code_str)

    def _get_logger(self, logger: Logger, context: RequestContext, **extra) -> Logger:
        """
        Create a logger with bound request context and extra data.

        The use case's own module is bound as well, and that is the one
        field a journal line carries about where a record came from. The
        logger arrives from the DI container, which fetched it under its
        own ``__name__`` -- so every line an application-layer use case
        wrote was filed under
        ``link_shortener.infrastructure.di.container``, and a reader
        filtering the journal by source found the wiring rather than the
        work. Measured on the running stack: ``Journal read refused``,
        written from ``ReadJournalUseCase``, arrived under the container's
        name.

        Bound rather than passed per call, because it is a property of the
        writer and not of the line.

        Args:
            logger: Raw logger instance.
            context: Request context.
            **extra: Additional key-value pairs to bind.

        Returns:
            A logger with bound fields.
        """
        ctx = context.for_logging()
        ctx["module"] = type(self).__module__
        ctx.update(extra)
        return logger.bind(**ctx)

    def _get_audit_logger(self, audit_logger: AuditLogger, context: RequestContext, **extra) -> AuditLogger:
        """
        Create an audit logger with bound request context.

        Args:
            audit_logger: Raw audit logger.
            context: Request context.
            **extra: Additional fields.

        Returns:
            An audit logger with bound fields.
        """
        ctx = context.for_logging()
        ctx.update(extra)
        return audit_logger.bind(**ctx)
