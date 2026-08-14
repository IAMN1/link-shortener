from dataclasses import dataclass

from link_shortener.domain.exceptions import ValidationError


@dataclass(frozen=True)
class OwnerID:
    """
    Value object representing the identifier of a link's owner.

    Isolates the domain from the concrete ID type (UUID string, integer, etc.).

    An owner-less link carries ``owner=None``, never ``OwnerID(None)``: two
    shapes for one state would make the same guest link differ by where it
    was read from, and every comparison between them wrong. Construction
    without a value is refused for that reason.

    Attributes:
        value: The raw owner identifier.
    """
    value: str

    def __post_init__(self):
        """
        Validate that an actual identifier was supplied.

        Raises:
            ValidationError: If the value is missing or empty.
        """
        if not self.value:
            raise ValidationError(
                "Owner id must not be empty. An owner-less link carries "
                "owner=None.",
                field="owner_id",
            )

    def __str__(self) -> str:
        """Return the raw identifier."""
        return self.value
