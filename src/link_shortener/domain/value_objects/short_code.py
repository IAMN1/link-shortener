import re
from dataclasses import dataclass

from link_shortener.domain.exceptions import ValidationError
from link_shortener.domain.i18n import N_


MIN_LENGTH = 6
"""Shortest code the domain accepts."""

MAX_LENGTH = 10
"""Longest code the domain accepts, and the width of the ``short_code`` column."""

CODE_PATTERN = re.compile(rf"[a-zA-Z0-9_-]{{{MIN_LENGTH},{MAX_LENGTH}}}")
"""The whole code, and nothing after it.

Matched with ``fullmatch``. Written as ``^...$`` and matched with ``match``
it accepted ``"abc123\\n"``, because ``$`` in Python also matches just
before a trailing newline -- so a code and the same code with a newline
were two different strings that both validated, one of which cannot go in a
cache key or a URL.
"""


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

        if not CODE_PATTERN.fullmatch(self.value):
            raise ValidationError(
                      f"Invalid short code format: {self.value}. "
                      f"Must be {MIN_LENGTH}-{MAX_LENGTH} alphanumeric characters, "
                      f"underscore, or hyphen.",
                      field="short_code",
                      template=N_(
                          "Invalid short code format: %(value)s. Must be "
                          "%(min)s-%(max)s alphanumeric characters, underscore, "
                          "or hyphen."
                      ),
                      params={
                          "value": self.value,
                          "min": MIN_LENGTH,
                          "max": MAX_LENGTH,
                      },
                  )

    def __str__(self) -> str:
        return self.value
