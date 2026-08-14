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
    
    @staticmethod
    def _refuse_unknown_permissions(requested: List[str], found) -> None:
        """
        Refuse a permission name the system does not know.

        Args:
            requested: Permission names as the caller wrote them.
            found: Permission entities the repository returned for them.

        Comparison is by name rather than by count, so a name repeated in
        the request is not mistaken for an unknown one.

        Raises:
            ValueError: If any requested name has no permission behind it.
        """
        missing = set(requested) - {permission.name for permission in found}
        if missing:
            raise ValueError(f"Permissions not found: {sorted(missing)}")

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
        self._refuse_unknown_permissions(permission_names, permissions)

        role = Role(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            is_system=False,
            permissions=tuple(permissions)
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
            ValueError: If the role does not exist, is a system role, or any
                requested permission does not exist.
        """
        role = uow.roles.get_by_name(role_name)
        if not role:
            raise ValueError(f"Role '{role_name}' not found")
        if role.is_system:
            raise ValueError("Cannot modify system roles")

        permissions = uow.permissions.get_by_names(permission_names)
        self._refuse_unknown_permissions(permission_names, permissions)

        updated_role = Role(
            id=role.id,
            name=role.name,
            description=role.description,
            is_system=role.is_system,
            permissions=tuple(permissions)
        )
        return uow.roles.save(updated_role)
    
    def delete_role(self, uow: UnitOfWork, role_name: str) -> None:
        """
        Delete a non-system role.

        Args:
            uow: Active unit of work.
            role_name: Name of the role to delete.

        Raises:
            LookupError: If the role does not exist.
            ValueError: If the role exists but may not be deleted.
        """
        # Two different answers, and they were one exception: "no such
        # role" and "that role is protected" both came back as ValueError,
        # so the endpoint answered 400 to a name that simply is not there
        # -- while the user endpoint next to it answered 404 for exactly
        # the same question.
        role = uow.roles.get_by_name(role_name)
        if not role:
            raise LookupError(f"Role '{role_name}' not found")
        if role.is_system:
            raise ValueError("Cannot delete system roles")
        uow.roles.delete(role.id)
