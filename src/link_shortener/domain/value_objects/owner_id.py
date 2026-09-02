from dataclasses import dataclass

from link_shortener.domain.exceptions import ValidationError
from link_shortener.domain.i18n import N_


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

        Whitespace counts as empty, the way it does for ``PasswordHash``
        next door: ``"   "`` is not an account any more than ``""`` is, and
        a scope token built from it -- ``u:   `` -- is a scope no owner
        can ever match again.

        Raises:
            ValidationError: If the value is missing, empty, or only
                whitespace.
        """
        if not self.value or not self.value.strip():
            raise ValidationError(
                N_("Owner id must not be empty. An owner-less link carries "
                "owner=None."),
                field="owner_id",
            )

    def __str__(self) -> str:
        """Return the raw identifier."""
        return self.value
