from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class OwnerID:
    """
    Value object representing the identifier of a link's owner.

    Isolates the domain from the concrete ID type (UUID string, integer, etc.).
    ``None`` represents a guest (non-authenticated) owner.

    Attributes:
        value: The raw owner identifier, or ``None`` for guest links.
    """
    value: Optional[str] # None if the link is guest

    def __str__(self) -> str:
        """Return the OwnerID as string, 'guest' if None."""
        return self.value if self.value else "guest"
