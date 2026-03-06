class DomainError(Exception):
    """Base exception for all domain layer errors."""

    def __init__(self, message: str, code: str = "DOMAIN_ERROR"):
        """
        Initialize a domain error.

        Args:
            message: Human-readable error description.
            code: Machine-readable error code (default: "DOMAIN_ERROR").
        """
        self.message = message
        self.code = code
        super().__init__(message)


class ValidationError(DomainError):
    """
    Exception raised for domain validation failures 
        (e.g., invalid URL format).
    """

    def __init__(self, message: str, field: str = None):
        """
        Initialize a validation error.

        Args:
            message: Error description.
            field: Optional field name that caused the validation error.
        """
        super().__init__(message, code="VALIDATION_ERROR")
        self.field = field


class LinkNotFoundError(DomainError):
    """Exception raised when a link cannot be found by its short code."""

    def __init__(self, short_code: str = None):
        """
        Initialize a link not found error.

        Args:
            short_code: Optional short code that was not found 
                (for detailed message).
        """
        self.short_code = short_code
        message = "Link not found"
        if short_code:
            message = f"Link with code ({short_code}) not found"
        super().__init__(message, "LINK_NOT_FOUND")
