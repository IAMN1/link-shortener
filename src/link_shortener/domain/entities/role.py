from dataclasses import dataclass
from typing import Optional, Tuple

from link_shortener.domain.entities.permission import Permission
from link_shortener.domain.exceptions import RoleIsSystemError


@dataclass(frozen=True)
class Role:
    """
    Domain entity representing a named collection of permissions.

    System roles (``is_system=True``) are protected: neither what they
    grant nor their existence can be changed through the application
    interface.

    Attributes:
        id: Unique identifier (UUID string).
        name: Unique role name (e.g., ``"admin"``, ``"user"``).
        description: Human-readable description of the role's purpose.
        is_system: If True, the role is considered a system role and cannot be
            deleted or modified via the API.
        permissions: The Permission objects assigned to this role.
    """
    id: str
    name: str                                           # admin, analyst, user
    description: Optional[str] = None
    is_system: bool = False                             # System roles cannot be deleted.
    permissions: Tuple[Permission, ...] = ()

    def __eq__(self, value):
        """Equality based on role ID."""
        if not isinstance(value, Role):
            return False
        return self.id == value.id

    def __hash__(self):
        """Hash based on role ID."""
        return hash(self.id)

    def ensure_may_be_changed(self) -> None:
        """
        Refuse a change to a role the service owns.

        Deletion counts as a change: both are refused by the same flag for
        the same reason, which is why one error carries both.

        The rule was written twice in ``RoleManagementService``, once
        before replacing a role's permissions and once before deleting it,
        and the flag it turns on lives here. A third caller would have had
        to remember -- and this entity is the thing that knows.

        Raises:
            RoleIsSystemError: If this is a role the service owns.
        """
        if self.is_system:
            raise RoleIsSystemError(self.name)

    def has_permission(self, permission_name: str) -> bool:
        """
        Check if this role grants a specific permission by name.

        Args:
            permission_name: The permission name to check (e.g., ``"link:create"``).

        Returns:
            True if the role contains a permission with the given name.
        """
        return any(p.name == permission_name for p in self.permissions)
