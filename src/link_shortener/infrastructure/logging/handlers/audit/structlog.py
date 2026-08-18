"""
Structlog adapter for audit events.

This module contains ``StructlogAuditLogger`` which implements the ``AuditLogger``
interface using the structlog library. It provides structured logging and
supports field binding.
"""

from typing import Optional, Any, Dict

import structlog

from link_shortener.application import AuditEvent, AuditLogger
from link_shortener.infrastructure.logging.utils import mask_email, mask_url


class StructlogAuditLogger(AuditLogger):
    """Audit logger implementation using structlog.

    This is the preferred implementation when structlog is available.
    It supports ``bind`` to attach contextual fields and uses a
    ``BoundLogger`` for efficient structured logging.

    Attributes:
        _logger: The underlying structlog ``BoundLogger``.
        _bound_fields: Dictionary of fields bound to this logger instance.
    """

    def __init__(self, bound_logger=None, bound_fields: Optional[Dict[str, Any]] = None):
        """Initialise the structlog audit logger.

        Args:
            bound_logger: An existing structlog ``BoundLogger``; if ``None``,
                a new logger for the ``"audit"`` namespace is created.
            bound_fields: Initial fields to bind.
        """
        self._bound_fields = bound_fields or {}
        if bound_logger is None:
            self._logger = structlog.get_logger("audit")
        else:
            self._logger = bound_logger

    def bind(self, **kwargs) -> "StructlogAuditLogger":
        """Return a new audit logger with additional bound fields.

        Args:
            **kwargs: Fields to bind (e.g. request_id, remote_addr).

        Returns:
            A new ``StructlogAuditLogger`` with the combined bound fields.
        """
        new_bound = {**self._bound_fields, **kwargs}
        new_logger = self._logger.bind(**kwargs)
        return StructlogAuditLogger(
            bound_logger=new_logger, bound_fields=new_bound
        )

    def _build_data(
        self,
        event_type: str,
        short_code: str,
        original_url: str,
        **kwargs
    ) -> dict:
        """Construct the dictionary of log fields for an audit event.

        The binding goes in first and everything else wins over it, which is
        how the sibling adapter ``StandardAuditLogger`` merges
        (``{**bound, **call}``) and how the library underneath resolves the
        same collision: ``event_dict = self._context.copy()`` and then
        ``event_dict.update(**event_kw)`` (``structlog._base``).

        Applied last, the binding would overwrite not only a
        field the call named but the event's own three: a logger bound with
        ``original_url`` put that value into the record in place of
        ``mask_url(original_url)``, so binding was a way round the masking.
        ``event_type`` and ``short_code`` went the same way, which is a
        record of one event filed under another.

        Args:
            event_type: Type of the audit event.
            short_code: Short code of the link.
            original_url: Original URL (will be masked).
            **kwargs: Additional contextual fields.

        Returns:
            Dictionary containing the event type, short code, masked
            original URL, all bound fields, and any extra kwargs.
        """
        data = dict(self._bound_fields)
        data.update({
            "event_type": event_type,
            "short_code": short_code,
            "original_url": mask_url(original_url),
        })
        data.update(kwargs)
        return data

    def log_url_created(self, short_code: str, original_url: str, **kwargs) -> None:
        """Log a URL creation event.

        Args:
            short_code: The generated short code.
            original_url: The original long URL.
            **kwargs: Additional context (e.g. batch_id, is_new).
        """
        data = self._build_data(
            event_type=AuditEvent.URL_CREATED.value,
            short_code=short_code,
            original_url=original_url,
            **kwargs
        )
        self._logger.info("Url created successfully", **data)

    def log_url_accessed(self, short_code: str, original_url: str, **kwargs) -> None:
        """Log a URL access (redirect) event.

        Args:
            short_code: The short code that was accessed.
            original_url: The original URL to which the user was redirected.
            **kwargs: Additional context (e.g. clicks count).
        """
        data = self._build_data(
            event_type=AuditEvent.URL_ACCESSED.value,
            short_code=short_code,
            original_url=original_url,
            **kwargs
        )
        self._logger.info("Url accessed successfully", **data)

    def log_url_deleted(self, short_code: str, original_url: str, **kwargs) -> None:
        """Log a URL deletion event.

        Args:
            short_code: The short code of the deleted link.
            original_url: The original long URL that was shortened.
            **kwargs: Additional context (e.g. request_id, remote_addr).
        """
        data = self._build_data(
            event_type=AuditEvent.URL_DELETED.value,
            short_code=short_code,
            original_url=original_url,
            **kwargs
        )
        self._logger.info("Url deleted successfully", **data)

    def log_security_event(self, event: AuditEvent, **fields) -> None:
        """Log an event about an account rather than about a link.

        ``email`` is masked on its way in, the way ``original_url`` is on
        the link events, and under the same rule: the field is masked
        because of the name it arrives under. An address passed as
        anything else -- or bound with ``bind()`` -- is written as given.

        ``event_type`` is written last and therefore cannot be overridden,
        by a bound field or by a keyword. See the reasoning in the sibling
        adapter ``StandardAuditLogger``: a context field is a caller's to
        override, the event's identity is not, and a record filed under the
        wrong ``event_type`` is one that a search for its own kind never
        returns.

        Args:
            event: Which event this is.
            **fields: The event's fields.
        """
        data = dict(self._bound_fields)
        data.update(fields)
        if "email" in data:
            data["email"] = mask_email(data["email"])
        data["event_type"] = event.value

        self._logger.info(f"Security event: {event.value}", **data)

    def is_healthy(self) -> bool:
        """Check whether the audit logger is operational.

        Returns:
            ``True`` if a simple debug log call succeeds, ``False`` otherwise.
        """
        try:
            self._logger.debug("health_check")
            return True
        except Exception:
            return False
