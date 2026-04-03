from abc import ABC, abstractmethod


class AuditLogger(ABC):
    """
    Interface for audit logging of significant events in the application.

    Audit logs are used for security, compliance, and monitoring purposes.
    Implementations may bind contextual fields (e.g., request ID, client IP)
    using the `bind` method and then log events with minimal arguments.

    All methods are designed to receive already resolved values (short_code,
    original_url) rather than domain objects to keep the interface decoupled
    from the domain layer.
    """

    @abstractmethod
    def bind(self, **kwargs) -> "AuditLogger":
        """
        Return a new audit logger instance with the provided fields bound.

        Bound fields are automatically included in every subsequent log call.
        This method is typically used to attach request context (request ID,
        remote address, user agent) to the logger.

        Args:
            **kwargs: Arbitrary key-value pairs to bind (e.g., request_id,
                remote_addr, user_agent).

        Returns:
            A new AuditLogger instance with the bound fields.
        """
        pass

    @abstractmethod
    def log_url_created(self, short_code: str, original_url: str, **kwargs) -> None:
        """
        Log the creation of a shortened URL.

        Args:
            short_code: The generated short code.
            original_url: The original long URL being shortened.
            **kwargs: Additional context (e.g., batch_id, is_new, from_cache).
        """
        pass

    @abstractmethod
    def log_url_accessed(self, short_code: str, original_url: str, **kwargs) -> None:
        """
        Log an access (redirect) event for a shortened URL.

        Args:
            short_code: The short code that was accessed.
            original_url: The original URL to which the user was redirected.
            **kwargs: Additional context (e.g., clicks count before increment).
        """
        pass

    @abstractmethod
    def log_url_deleted(self, short_code: str, original_url: str, **kwargs) -> None:
        """Log deletion of a shortened URL."""
        pass