from dataclasses import dataclass
from typing import List, Optional


from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.admin.role import RoleResponse
from link_shortener.application.dtos.user import UserResponse
from link_shortener.application.use_cases.admin.roles.create_role import CreateRoleUseCase
from link_shortener.application.use_cases.admin.roles.delete_role import DeleteRoleUseCase
from link_shortener.application.use_cases.admin.roles.get_role import GetRoleUseCase
from link_shortener.application.use_cases.admin.roles.list_roles import ListRolesUseCase
from link_shortener.application.use_cases.admin.roles.update_role_permissions import UpdateRolePermissionsUseCase
from link_shortener.application.use_cases.admin.users.activate_user import ActivateUserUseCase
from link_shortener.application.use_cases.admin.users.create_user import CreateUserUseCase
from link_shortener.application.use_cases.admin.users.deactivate_user import DeactivateUserUseCase
from link_shortener.application.use_cases.admin.users.delete_user import DeleteUserUseCase
from link_shortener.application.use_cases.admin.users.get_user import GetUserUseCase
from link_shortener.application.use_cases.admin.users.list_user import ListUsersUseCase
from link_shortener.application.use_cases.admin.users.update_user_role import UpdateUserRolesUseCase


@dataclass
class AdminService:
    """
    Facade for administrative operations (user and role management).

    Delegates to dedicated use cases while providing a simplified interface
    for the web layer.
    """

    create_user_uc: CreateUserUseCase
    update_user_roles_uc: UpdateUserRolesUseCase
    deactivate_user_uc: DeactivateUserUseCase
    activate_user_uc: ActivateUserUseCase
    list_users_uc: ListUsersUseCase
    get_user_uc: GetUserUseCase
    delete_user_uc: DeleteUserUseCase
    create_role_uc: CreateRoleUseCase
    update_role_permissions_uc: UpdateRolePermissionsUseCase
    delete_role_uc: DeleteRoleUseCase
    list_roles_uc: ListRolesUseCase
    get_role_uc: GetRoleUseCase

    # ------------------------------------------------------------------
    # User management
    # ------------------------------------------------------------------
    def create_user(
        self,
        email: str,
        password: str,
        context: RequestContext,
        role_names: Optional[List[str]] = None,
        is_active: bool = True,
    ) -> UserResponse:
        """
        Create a new user account via the admin panel.

        Args:
            email: User's email address.
            password: Plain-text password.
            context: Request context containing admin's identity.
            role_names: Optional list of role names to assign; uses default
                role when omitted.
            is_active: Whether the account should be enabled immediately.

        Returns:
            UserResponse with the newly created user's details.
        """
        return self.create_user_uc.execute(
            email=email,
            password=password,
            context=context,
            role_names=role_names,
            is_active=is_active,
        )

    def list_users(
        self, context: RequestContext, limit: int = 100, offset: int = 0
    ) -> List[UserResponse]:
        """
        Return a paginated list of all users.

        Args:
            context: Request context with admin's identity.
            limit: Maximum number of users to return.
            offset: Number of users to skip.

        Returns:
            List of UserResponse objects.
        """
        return self.list_users_uc.execute(context, limit=limit, offset=offset)

    def get_user(self, user_id: str, context: RequestContext) -> Optional[UserResponse]:
        """
        Fetch a single user by identifier.

        Args:
            user_id: UUID of the user.
            context: Request context.

        Returns:
            UserResponse if found, else ``None``.
        """
        return self.get_user_uc.execute(user_id, context)

    def update_user_roles(
        self, user_id: str, role_names: List[str], context: RequestContext
    ) -> UserResponse:
        """
        Replace the roles assigned to a user.

        Args:
            user_id: UUID of the user.
            role_names: New list of role names.
            context: Request context with admin's identity.

        Returns:
            Updated UserResponse.
        """
        return self.update_user_roles_uc.execute(
            user_id=user_id,
            role_names=role_names,
            context=context,
        )

    def deactivate_user(self, user_id: str, context: RequestContext) -> UserResponse:
        """
        Deactivate a user account (soft delete).

        Args:
            user_id: UUID of the user.
            context: Request context.

        Returns:
            UserResponse with active flag set to False.
        """
        return self.deactivate_user_uc.execute(user_id, context)

    def activate_user(self, user_id: str, context: RequestContext) -> UserResponse:
        """
        Reactivate a previously deactivated user account.

        Args:
            user_id: UUID of the user.
            context: Request context.

        Returns:
            UserResponse with active flag set to True.
        """
        return self.activate_user_uc.execute(user_id, context)

    def delete_user(self, user_id: str, context: RequestContext) -> bool:
        """
        Permanently delete a user.

        Args:
            user_id: UUID of the user.
            context: Request context.

        Returns:
            ``True`` if the user was deleted, ``False`` if not found.
        """
        return self.delete_user_uc.execute(user_id, context)

    # ------------------------------------------------------------------
    # Role management
    # ------------------------------------------------------------------
    def create_role(
        self,
        name: str,
        description: Optional[str],
        permission_names: List[str],
        context: RequestContext,
    ) -> RoleResponse:
        """
        Create a new role with the given permissions.

        Args:
            name: Unique role name.
            description: Optional human-readable description.
            permission_names: List of permission names to assign.
            context: Request context with admin's identity.

        Returns:
            RoleResponse representing the newly created role.
        """
        return self.create_role_uc.execute(
            name=name,
            description=description,
            permission_names=permission_names,
            context=context,
        )

    def list_roles(self, context: RequestContext) -> List[RoleResponse]:
        """
        Return all roles defined in the system.

        Args:
            context: Request context.

        Returns:
            List of RoleResponse objects.
        """
        return self.list_roles_uc.execute(context)

    def get_role(self, role_name: str, context: RequestContext) -> Optional[RoleResponse]:
        """
        Fetch a single role by name.

        Args:
            role_name: Role name to look up.
            context: Request context.

        Returns:
            RoleResponse if found, else ``None``.
        """
        return self.get_role_uc.execute(role_name, context)

    def update_role_permissions(
        self, role_name: str, permission_names: List[str], context: RequestContext
    ) -> RoleResponse:
        """
        Replace the permission set of a role.

        Args:
            role_name: Role to update.
            permission_names: New list of permission names.
            context: Request context.

        Returns:
            Updated RoleResponse.
        """
        return self.update_role_permissions_uc.execute(
            role_name=role_name,
            permission_names=permission_names,
            context=context,
        )

    def delete_role(self, role_name: str, context: RequestContext) -> bool:
        """
        Delete a non-system role.

        Args:
            role_name: Role name to delete.
            context: Request context.

        Returns:
            ``True`` if deleted, ``False`` if role is system or not found.
        """
        return self.delete_role_uc.execute(role_name, context)
