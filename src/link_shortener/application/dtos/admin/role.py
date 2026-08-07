from dataclasses import dataclass
from typing import List, Optional

from link_shortener.domain import Role
from link_shortener.application.dtos.admin.permission import PermissionResponse


@dataclass
class RoleResponse:
    """
    DTO for returning role data.

    Attributes:
        id: Unique role identifier.
        name: Role name.
        description: Optional description.
        is_system: Whether it's a system role (protected).
        permissions: List of permissions assigned to this role.
    """
    id: str
    name: str
    description: Optional[str]
    is_system: bool
    permissions: List[PermissionResponse]

    @classmethod
    def from_role(cls, role: Role) -> "RoleResponse":
        """
        Create a DTO from a domain Role entity.

        Args:
            role: The domain Role object.

        Returns:
            RoleResponse with permissions recursively mapped.
        """
        return cls(
            id=role.id,
            name=role.name,
            description=role.description,
            is_system=role.is_system,
            permissions=[PermissionResponse.from_permission(p) for p in role.permissions],
        )
