import re
from dataclasses import dataclass

from link_shortener.domain.exceptions import ValidationError
from link_shortener.domain.i18n import N_


HASH_PATTERN = re.compile(r"[a-f0-9]{64}")
"""The whole digest, and nothing after it.

Matched with ``fullmatch``, for the reason ``short_code.CODE_PATTERN``
spells out: written as ``^...$`` and matched with ``match`` it accepted a
digest with a trailing newline, because ``$`` in Python also matches just
before a newline at the end of the string. Two strings would then be two
different hashes that both validated, one of which cannot go in a cache
key -- and the deduplication entry is keyed by exactly this value.
"""


@dataclass(frozen=True)
class UrlHash:
    """
    Value object representing a SHA-256 hash of a URL.

    Used for deduplication. Format enforced: **64 lowercase hexadecimal characters**.

    Examples:
        ``"e41bc44298fc1c149afbf4c8996fb94432ae41e11519b934da495991c7852911"``
        (example uses a valid-looking hash; actual validation allows only ``[a-f0-9]``).

    Attributes:
        value: The 64-character hex string.
    """

    value: str

    def __post_init__(self):
        """
        Validate that the hash is exactly 64 lowercase hexadecimal characters.

        Raises:
            ValidationError: If the hash does not match the required pattern.
        """

        if not HASH_PATTERN.fullmatch(self.value):
            raise ValidationError(
                      f"Invalid hash format: {self.value}. Must be 64 hex characters.",
                      field="url_hash",
                      template=N_(
                          "Invalid hash format: %(value)s. Must be 64 hex characters."
                      ),
                      params={"value": self.value},
                  )

    def __str__(self) -> str:
        return self.value
