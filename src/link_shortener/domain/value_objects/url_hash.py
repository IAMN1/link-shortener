import re
from dataclasses import dataclass


@dataclass(frozen=True)
class UrlHash:
    """
    Value object representing a SHA-256 hash of a URL.

    Used for deduplication. Format: 64 lowercase hex characters.
    """

    value: str

    def __post_init__(self):
        """Validate hash format (64 hex chars)."""

        if not re.match(r"^[a-f0-9]{64}$", self.value):
            raise ValueError(
                f"Invalid hash format: {self.value}. " f"Must be 64 hex characters."
            )

    def __str__(self) -> str:
        return self.value
