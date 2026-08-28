from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Permission:
    """
    Domain entity representing a fine-grained permission (e.g., ``link:create``).

    Permissions are immutable and identified by their unique name. They define
    a specific action that can be performed on a resource.

    Attributes:
        id: Unique identifier (UUID string).
        name: Globally unique permission name, following the ``resource:action``
            convention.
        resource: The domain resource this permission applies to (e.g., ``"link"``).
        action: The operation allowed (e.g., ``"create"``).
        description: Human-readable explanation of what the permission grants.
    """
    id: str
    name: str                           # e.g., "link:create"
    resource: str                       # e.g., "link"
    action: str                         # e.g., "create"
    description: Optional[str] = None

    def __eq__(self, value) -> bool:
        """
        Equality based on permission ID.

        Args:
            value: Another Permission instance to compare.

        Returns:
            True if IDs match.
        """
        if not isinstance(value, Permission):
            return False
        return self.id == value.id

    def __hash__(self) -> int:
        """Hash based on permission ID."""
        return hash(self.id)
