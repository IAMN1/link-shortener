from dataclasses import dataclass
import re

from link_shortener.domain.exceptions import ValidationError


@dataclass(frozen=True)
class Email:
    """
    Value object representing an email address.

    Immutable; validates that the string conforms to a basic email format
    (``local-part@domain.tld``) upon creation.

    Attributes:
        value: The email string.
    """
    value: str

    def __post_init__(self):
        """
        Validate the email format immediately after initialisation.

        Raises:
            ValidationError: If the email does not match the expected pattern.
        """
        if not re.match(r"^[^@]+@[^@]+\.[^@]+$", self.value):
            raise ValidationError(f"Invalid email format: {self.value}", field="email")
    
    def __str__(self) -> str:
        """Return the email string."""
        return self.value
