from dataclasses import dataclass, field
from typing import List, Optional

from link_shortener.domain.entities.permission import Permission


@dataclass(frozen=True)
class Role:
    """
    Domain entity representing a named collection of permissions.

    System roles (``is_system=True``) are protected and cannot be deleted through
    the application interface.

    Attributes:
        id: Unique identifier (UUID string).
        name: Unique role name (e.g., ``"admin"``, ``"user"``).
        description: Human-readable description of the role's purpose.
        is_system: If True, the role is considered a system role and cannot be
            deleted or modified via the API.
        permissions: List of Permission objects assigned to this role.
    """
    id: str
    name: str                                           # admin, analyst, user
    description: Optional[str] = None
    is_system: bool = False                             # Системные роли нельзя удалить
    permissions: List[Permission] = field(default_factory=list)

    def __eq__(self, value):
        """Equality based on role ID."""
        if not isinstance(value, Role):
            return False
        return self.id == value.id
    
    def __hash__(self):
        """Hash based on role ID."""
        return hash(self.id)
    
    def has_permission(self, permission_name: str) -> bool:
        """
        Check if this role grants a specific permission by name.

        Args:
            permission_name: The permission name to check (e.g., ``"link:create"``).

        Returns:
            True if the role contains a permission with the given name.
        """
        return any(p.name == permission_name for p in self.permissions)
