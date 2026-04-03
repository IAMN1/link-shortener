from abc import ABC
from dataclasses import asdict

from link_shortener.application.context import RequestContext
from link_shortener.application import Logger
from link_shortener.application.ports.logger.audit import AuditLogger


class BaseUseCase(ABC):
    """
    Base class for all use cases.

    Provides helper methods to obtain loggers and audit loggers with
    automatically bound request context fields (request_id, remote_addr,
    user_agent, request_path, request_method).
    """

    def _get_logger(self, logger: Logger, context: RequestContext, **extra) -> Logger:
        """
        Return a logger with bound fields from the request context and extra data.

        Args:
            logger: The original logger instance.
            context: RequestContext containing request metadata.
            **extra: Additional key-value pairs to bind (usecase-specific).

        Returns:
            A logger with the bound fields (may be a new instance).
        """
        # asdict преобразует все поля dataclass в словарь
        return logger.bind(**asdict(context), **extra)
    
    def _get_audit_logger(self, audit_logger: AuditLogger, context: RequestContext, **extra) -> AuditLogger:
        """
        Return an audit logger with bound fields from the request context and extra data.

        Args:
            audit_logger: The original audit logger instance.
            context: RequestContext containing request metadata.
            **extra: Additional key-value pairs to bind.

        Returns:
            An audit logger with the bound fields.
        """
        return audit_logger.bind(**asdict(context), **extra)