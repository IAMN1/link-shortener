from typing import List
import uuid

from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.domain import Role


class RoleManagementService:
    """
    Service for managing roles (used by admin use cases).

    Encapsulates creation, permission updates, and deletion of roles,
    ensuring system roles are protected.
    """
    
    def create_role(self,
                    uow: UnitOfWork,
                    name: str,
                    description: str,
                    permission_names: List[str]
    ) -> Role:
        """
        Create a new non-system role with specified permissions.

        Args:
            uow: Active unit of work.
            name: Unique role name.
            description: Human-readable description.
            permission_names: List of permission names to assign.

        Returns:
            The newly created Role entity.

        Raises:
            ValueError: If the role name already exists or any permission is missing.
        """
        existing = uow.roles.get_by_name(name)
        if existing:
            raise ValueError(f"Role '{name}' already exists")
        permissions = uow.permissions.get_by_names(permission_names)

        if len(permissions) != len(permission_names):
            missing = set(permission_names) - {p.name for p in permissions}
            raise ValueError(f"Permissions not found: {missing}")
        
        role = Role(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            is_system=False,
            permissions=permissions
        )
        return uow.roles.save(role)
    
    def update_role_permissions(self, uow: UnitOfWork, role_name: str, permission_names: List[str]) -> Role:
        """
        Replace the permissions of an existing role.

        Args:
            uow: Active unit of work.
            role_name: Role to update.
            permission_names: New list of permission names.

        Returns:
            Updated Role entity.

        Raises:
            ValueError: If the role does not exist or is a system role.
        """
        role = uow.roles.get_by_name(role_name)
        if not role:
            raise ValueError(f"Role '{role_name}' not found")
        if role.is_system:
            raise ValueError("Cannot modify system roles")
        
        permissions = uow.permissions.get_by_names(permission_names)
        role.permissions = permissions
        return uow.roles.save(role)
    
    def delete_role(self, uow: UnitOfWork, role_name: str) -> None:
        """
        Delete a non-system role.

        Args:
            uow: Active unit of work.
            role_name: Name of the role to delete.

        Raises:
            ValueError: If role not found or is a system role.
        """
        role = uow.roles.get_by_name(role_name)
        if not role:
            raise ValueError(f"Role '{role_name}' not found")
        if role.is_system:
            raise ValueError("Cannot delete system roles")
        uow.roles.delete(role.id)
