from typing import Any, Dict, Optional

from link_shortener.domain.i18n import N_


class DomainError(Exception):
    """
    Base exception for all domain layer errors.

    This class serves as the root of the domain-specific exception hierarchy.
    All domain errors should inherit from it so that they can be caught and
    handled uniformly in the application layer.

    Attributes:
        message: Human-readable error description, in English. What the
            logs keep and what a caller that does not translate sees.
        code: Machine-readable error code (default ``"DOMAIN_ERROR"``)
        template: The msgid the boundary looks the sentence up by, with
            named placeholders where values go. Defaults to ``message``,
            which is right for every sentence that has no values in it.
        params: What those placeholders stand for.
    """

    def __init__(
        self,
        message: str,
        code: str = "DOMAIN_ERROR",
        *,
        template: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ):
        self.message = message
        self.code = code
        # Carried beside the finished sentence rather than instead of it.
        # The message is what `application.log` records and what the CLI
        # prints, and neither of those has a reader to negotiate a
        # language with; the template is for the one caller that does.
        self.template = template if template is not None else message
        self.params: Dict[str, Any] = params or {}
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

    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        *,
        template: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message, code="VALIDATION_ERROR", template=template, params=params
        )
        self.field = field


class LinkNotFoundError(DomainError):
    """
    Exception raised when a link cannot be found by its short code.

    Attributes:
        message: Descriptive error message (includes short_code if provided).
        code: Always ``"LINK_NOT_FOUND"``.
        short_code: The short code that was searched for, if known.
    """

    def __init__(self, short_code: Optional[str] = None):
        self.short_code = short_code
        if short_code:
            super().__init__(
                f"Link with code ({short_code}) not found",
                "LINK_NOT_FOUND",
                template=N_("Link with code (%(code)s) not found"),
                params={"code": short_code},
            )
        else:
            super().__init__(N_("Link not found"), "LINK_NOT_FOUND")

class CodeGenerationError(DomainError):
    """
    Raised when the system fails to generate a unique short code after
    exhausting all collision-resolution attempts.

    Attributes:
        message: Default message explaining the failure.
        code: Always ``"CODE_GENERATION_FAILED"``.
    """
    def __init__(
        self,
        # Not marked: this code maps to 500, and a 5xx sentence never
        # reaches a reader -- the handler answers the generic one. Marking
        # it would put a sentence about the service's internals in front
        # of a translator with no way to see where it appears.
        message: str = "Failed to generate unique short code after multiple attempts",
    ):
        super().__init__(message, code="CODE_GENERATION_FAILED")

class LinkConflictError(DomainError):
    """
    Raised when a link could not be stored because another one got there first.

    Uniqueness of a short code is decided by the database, not by a lookup
    beforehand: two requests that both check and then both insert are a
    check-then-insert race. Storage reports the conflict and the caller
    retries; by then the winner's row is visible, so the retry either
    returns it or picks a different code.

    Attributes:
        message: Error description.
        code: Always ``"LINK_CONFLICT"``.
    """

    def __init__(
        self,
        message: str = "Link conflicts with one stored concurrently",
    ):
        super().__init__(message, code="LINK_CONFLICT")


class LinkCodeTakenError(DomainError):
    """Raised when a code the caller chose is already in use.

    Distinct from ``LinkConflictError``, which means a *generated* code lost
    a race and another one will do. This one has no retry behind it: the
    caller asked for one particular code, and answering with a different one
    would look like the request succeeded.
    """

    def __init__(self, short_code: str):
        self.short_code = short_code
        super().__init__(
            f"Short code '{short_code}' is already taken",
            "LINK_CODE_TAKEN",
            template=N_("Short code '%(code)s' is already taken"),
            params={"code": short_code},
        )


class LinkExpiredError(DomainError):
    """Raised when an expired link is accessed."""
    def __init__(self, short_code_str: str):
        self.short_code_str = short_code_str
        if short_code_str:
            super().__init__(
                f"Link with code ({short_code_str}) has expired",
                "LINK_EXPIRED",
                template=N_("Link with code (%(code)s) has expired"),
                params={"code": short_code_str},
            )
        else:
            super().__init__(N_("Link has expired"), "LINK_EXPIRED")

class GuestLinkLimitExceededError(DomainError):
    """Raised when the guest link creation limit is exceeded.

    Attributes:
        retry_after_seconds: How long the window lasts, so the answer can
            say when it is worth trying again. Without it the refusal was
            indistinguishable from the rate limiter's own 429, which clears
            in a minute -- this one clears in a day.
    """

    def __init__(
        self,
        message: str = N_("Guest link limit exceeded"),
        retry_after_seconds: Optional[int] = None,
        *,
        template: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message, "GUEST_LINK_LIMIT", template=template, params=params
        )
        self.retry_after_seconds = retry_after_seconds
