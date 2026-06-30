import re
from dataclasses import dataclass

from link_shortener.domain.exceptions import ValidationError


@dataclass(frozen=True)
class ShortCode:
    """
    Value object representing a generated short code.

    Immutable, with validation ensuring the code matches the required format:
    **6-10 alphanumeric characters, underscore, or hyphen**.

    Examples:
        - ``"abc123"``
        - ``"my_code"``
        - ``"short-x"``

    Attributes:
        value: The short code string.
    """

    value: str

    def __post_init__(self):
        """
        Validate the short code format upon creation.

        Raises:
            ValidationError: If the code does not match the required pattern.
        """

        if not re.match(r"^[a-zA-Z0-9_-]{6,10}$", self.value):
            raise ValidationError(
                f"Invalid short code format: {self.value}. "
                f"Must be 6-10 alphanumeric characters, underscore, or hyphen.",
                field="short_code",
            )

    def __str__(self) -> str:
        return self.value

    @classmethod
    def create(cls, value: str) -> "ShortCode":
        """
        Factory method with explicit validation (alternative to constructor).

        Args:
            value: Short code string.

        Returns:
            ShortCode instance.
        """
        return cls(value)
