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
            # The offending value is deliberately left out: this message
            # reaches the client, and the same object is built from database
            # rows, so echoing it would reflect user input and leak stored
            # data on the read path.
            raise ValidationError("Invalid email format", field="email")
    
    def __str__(self) -> str:
        """Return the email string."""
        return self.value
