import re
from dataclasses import dataclass


@dataclass(frozen=True)
class UrlHash:
    """
    Value object representing a SHA-256 hash of a URL.

    Used for deduplication. Format: 64 lowercase hex characters.

    Examples:
        - "e41bc44298fc1c149afbf4c8996fb94432ae41e11519b934da495991c7852v911"
    """

    value: str

    def __post_init__(self):
        """
        Validate the hash format (64 lowercase hex characters).

        Raises:
            ValueError: If the hash does not match the required pattern.
        """

        if not re.match(r"^[a-f0-9]{64}$", self.value):
            raise ValueError(
                f"Invalid hash format: {self.value}. " f"Must be 64 hex characters."
            )

    def __str__(self) -> str:
        return self.value
