class DomainError(Exception):
    """
    Base exception for all domain layer errors.

    This class serves as the root of the domain-specific exception hierarchy.
    All domain errors should inherit from it so that they can be caught and
    handled uniformly in the application layer.

    Attributes:
        message: Human-readable error description.
        code: Machine-readable error code (default ``"DOMAIN_ERROR"``)
    """

    def __init__(self, message: str, code: str = "DOMAIN_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class ValidationError(DomainError):
    """
    Exception raised for domain validation failures.

    This typically originates from value objects when an invalid value is provided
    (e.g., malformed URL, email, or short code).

    Attributes:
        message: Error description.
        code: Always ``"VALIDATION_ERROR"``.
        field: Optional name of the field that caused the validation error.
    """

    def __init__(self, message: str, field: str = None):
        super().__init__(message, code="VALIDATION_ERROR")
        self.field = field


class LinkNotFoundError(DomainError):
    """
    Exception raised when a link cannot be found by its short code.

    Attributes:
        message: Descriptive error message (includes short_code if provided).
        code: Always ``"LINK_NOT_FOUND"``.
        short_code: The short code that was searched for, if known.
    """

    def __init__(self, short_code: str = None):
        self.short_code = short_code
        message = "Link not found"
        if short_code:
            message = f"Link with code ({short_code}) not found"
        super().__init__(message, "LINK_NOT_FOUND")

class CodeGenerationError(DomainError):
    """
    Raised when the system fails to generate a unique short code after
    exhausting all collision-resolution attempts.

    Attributes:
        message: Default message explaining the failure.
        code: Always ``"CODE_GENERATION_FAILED"``.
    """
    def __init__(self, message: str = "Failed to generate unique short code after multiple attempts"):
        super().__init__(message, code="CODE_GENERATION_FAILED")
