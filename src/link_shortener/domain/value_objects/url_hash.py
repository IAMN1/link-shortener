import re
from dataclasses import dataclass


@dataclass(frozen=True)
class UrlHash:
    """
    Value object для хэша URL
    Используется для дедупликации
    """

    value: str

    def __post_init__(self):
        if not re.match(r"^[a-f0-9]{64}$", self.value):
            raise ValueError(
                f"Invalid hash format: {self.value}. " f"Must be 64 hex characters."
            )

    def __str__(self) -> str:
        return self.value
