from abc import ABC

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger


class BaseUseCase(ABC):
    """
    Base class for all use cases.

    Provides helper methods to obtain loggers and audit loggers with
    automatically bound request context (request_id, remote_addr, etc.).
    """

    def _get_logger(self, logger: Logger, context: RequestContext, **extra) -> Logger:
        """
        Create a logger with bound request context and extra data.

        Args:
            logger: Raw logger instance.
            context: Request context.
            **extra: Additional key-value pairs to bind.

        Returns:
            A logger with bound fields.
        """
        ctx = context.for_logging()
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
