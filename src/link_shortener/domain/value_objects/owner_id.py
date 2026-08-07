from dataclasses import dataclass

from link_shortener.domain.exceptions import ValidationError


@dataclass(frozen=True)
class OwnerID:
    """
    Value object representing the identifier of a link's owner.

    Isolates the domain from the concrete ID type (UUID string, integer, etc.).

    An owner-less link carries ``owner=None``, never ``OwnerID(None)``. The
    two used to coexist -- the repository returned one, the factory and the
    cache the other -- so the same guest link arrived in different shapes
    depending on where it was read from, and any comparison between them was
    quietly wrong. Refusing to be constructed without a value is what keeps
    the second shape from coming back.

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
