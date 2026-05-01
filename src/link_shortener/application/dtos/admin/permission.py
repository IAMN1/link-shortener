from dataclasses import dataclass
from typing import Optional

from link_shortener.domain import Permission


@dataclass
class PermissionResponse:
    """
    DTO for returning permission data (e.g., in admin API).

    Attributes:
        id: Unique permission identifier.
        name: Permission name (resource:action format).
        resource: Target resource.
        action: Allowed action.
        description: Human-readable explanation, if any.
    """
    id: str
    name: str
    resource: str
    action: str
    description: Optional[str] = None

    @classmethod
    def from_permission(cls, permission: Permission) -> "PermissionResponse":
        """
        Create a DTO from a domain Permission entity.

        Args:
            permission: The domain Permission object.

        Returns:
            PermissionResponse with all fields mapped.
        """
        return cls(
            id=permission.id,
            name=permission.name,
            resource=permission.resource,
            action=permission.action,
            description=permission.description,
        )
