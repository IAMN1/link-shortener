"""
Standard Python logging adapter for audit events.

This module provides the ``StandardAuditLogger`` which implements the
``AuditLogger`` interface using the standard library's ``logging`` module.
It can be used as a primary or fallback audit logger.
"""

import logging
from typing import Optional, Any, Dict

from link_shortener.application import AuditEvent, AuditLogger
from link_shortener.infrastructure.logging.utils import (
    HEALTH_PROBE_FIELDS, HEALTH_PROBE_MESSAGE, mask_email, mask_url,
    probe_level,
)


class StandardAuditLogger(AuditLogger):
    """Audit logger using the standard ``logging`` module.

    Bound fields are stored internally and passed via the ``extra`` keyword
    argument on every log call. The ``original_url`` of an event is masked
    on its way in -- and only that one: an address passed under any other
    name, whether in ``**kwargs`` or bound with ``bind()``, is recorded as
    given. ``mask_url`` also leaves query strings alone, so a token in one
    survives even the field that is masked.

    Attributes:
        _logger: The underlying ``logging.Logger`` instance.
        _bound_fields: Dictionary of contextual fields bound to the logger.
    """

    def __init__(self, name: str = "audit", bound_fields: Optional[Dict[str, Any]] = None):
        """Initialise the standard audit logger.

        Args:
            name: Name of the logger (default ``"audit"``).
            bound_fields: Initial dictionary of bound fields.
        """
        self._logger = logging.getLogger(name)
        self._bound_fields = bound_fields or {}

    def bind(self, **kwargs) -> "StandardAuditLogger":
        """Return a new audit logger with additional bound fields.

        Args:
            **kwargs: Fields to bind (e.g. request_id, remote_addr).

        Returns:
            A new ``StandardAuditLogger`` instance with the combined bound fields.
        """
        return StandardAuditLogger(
            name=self._logger.name,
            bound_fields={**self._bound_fields, **kwargs}
        )

    def _log(self, event: str, **kwargs):
        """Internal logging helper.

        Args:
            event: Event name (e.g. ``"URL_CREATED"``).
            **kwargs: Structured data to include in the log record.
        """
        all_fields = {**self._bound_fields, **kwargs}
        self._logger.info(event, extra=all_fields)

    def _build_data(
        self,
        event_type: str,
        short_code: str,
        original_url: str,
        **kwargs
    ) -> dict:
        """Construct the dictionary of log fields for an audit event.

        Args:
            event_type: Type of the audit event.
            short_code: Short code of the link.
            original_url: Original URL (will be masked).
            **kwargs: Additional contextual fields.

        Returns:
            Dictionary containing the event type, short code, masked
            original URL, and any extra fields.
        """
        data = {
            "event_type": event_type,
            "short_code": short_code,
            "original_url": mask_url(original_url),
        }
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
        self._log("Url created successfully", **data)

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
        self._log("Url accessed successfully", **data)

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
        self._log("Url deleted successfully", **data)

    def log_security_event(self, event: AuditEvent, **fields) -> None:
        """Log an event about an account rather than about a link.

        ``email`` is masked on its way in, the way ``original_url`` is on
        the link events, and under the same rule: the field is masked
        because of the name it arrives under. An address passed as
        anything else -- or bound with ``bind()`` -- is written as given.

        ``event_type`` is written last and therefore cannot be overridden,
        which is where this method parts company with the link events above
        it: there, a caller's keyword wins over the event's own fields.
        The argument for letting it win is that a caller knows its own
        context better than the method does, and that holds for a context
        field. It does not hold for the event's identity. A record filed
        under the wrong ``event_type`` is not a record with a wrong field
        in it -- it is a login that a search for logins will never return,
        and the search will answer "none" rather than "cannot say".

        Args:
            event: Which event this is.
            **fields: The event's fields.
        """
        # The bound fields are merged in here rather than left to ``_log``,
        # which merges them too. Left to it, an address bound under
        # ``email`` would arrive after the masking and reach the record
        # whole -- binding would be the way around the mask, which is the
        # defect the link events had and were fixed for.
        data = {**self._bound_fields, **fields}
        if "email" in data:
            data["email"] = mask_email(data["email"])
        data["event_type"] = event.value

        self._log(f"Security event: {event.value}", **data)

    def is_healthy(self) -> bool:
        """Check whether the audit logger is operational.

        Asked of the hierarchy, as ``StandardLogger.is_healthy`` is: the
        audit logger is given its own handlers here and stops propagation,
        so the two questions have the same answer today -- but a
        configuration that let audit records travel to the root would have
        this one call itself unwell while they arrived.

        Written at the level this logger actually passes records at, for
        the reason ``probe_level`` gives. The audit handlers are set to
        ``INFO`` unconditionally, so the old ``DEBUG`` probe could not
        reach one under any configuration: this chain answered ``True``
        about itself whatever state it was in.

        Returns:
            ``True`` if a handler is reachable from this logger and a
            health-check message can be written, ``False`` otherwise.
        """
        if not self._logger.hasHandlers():
            return False
        level = probe_level(self._logger.name)
        try:
            # Create a temporary logger sharing the same handlers
            test_logger = logging.getLogger(self._logger.name + "._health_test")
            test_logger.handlers = self._logger.handlers
            test_logger.propagate = False
            test_logger.setLevel(level)
            test_logger.log(level, HEALTH_PROBE_MESSAGE, extra=dict(HEALTH_PROBE_FIELDS))
            return True
        except Exception:
            return False
        finally:
            # Clean up temporary logger to avoid memory leaks
            logging.Logger.manager.getLogger(
                self._logger.name + "._health_test"
            ).handlers = []
