from link_shortener.application.ports.logger.audit import AuditEvent, AuditLogger


class NullAuditLogger(AuditLogger):
    """
    Null-object implementation of AuditLogger.

    All audit events are silently discarded.
    Used when audit logging is disabled (AUDIT_ENABLED=False) or as a fallback.
    """

    def bind(self, **kwargs) -> "NullAuditLogger":
        """
        Return the same instance (no fields are stored).

        Returns:
            self (no effect).
        """
        return self

    def log_url_created(self, short_code: str, original_url: str, **kwargs) -> None:
        """No-op: do nothing."""
        pass

    def log_url_accessed(self, short_code: str, original_url: str, **kwargs) -> None:
        """No-op: do nothing."""
        pass

    def log_url_deleted(self, short_code: str, original_url: str, **kwargs) -> None:
        """No-op: do nothing."""
        pass

    def log_security_event(self, event: AuditEvent, **fields) -> None:
        """No-op: do nothing."""
        pass

    def is_healthy(self):
        """Null logger is always healthy."""
        return True
