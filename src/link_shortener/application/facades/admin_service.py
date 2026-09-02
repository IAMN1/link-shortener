from dataclasses import dataclass
from typing import List, Optional, Tuple


from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.admin.role import RoleResponse
from link_shortener.application.dtos.user import UserResponse
from link_shortener.application.dtos.user_activity import UserActivityResponse
from link_shortener.application.use_cases.admin.roles.create_role import CreateRoleUseCase
from link_shortener.application.use_cases.admin.roles.delete_role import DeleteRoleUseCase
from link_shortener.application.use_cases.admin.roles.get_role import GetRoleUseCase
from link_shortener.application.use_cases.admin.roles.list_roles import ListRolesUseCase
from link_shortener.application.use_cases.admin.roles.update_role_permissions import UpdateRolePermissionsUseCase
from link_shortener.application.use_cases.admin.users.activate_user import ActivateUserUseCase
from link_shortener.application.use_cases.admin.users.create_user import CreateUserUseCase
from link_shortener.application.use_cases.admin.users.confirm_user_email import ConfirmUserEmailUseCase
from link_shortener.application.use_cases.admin.users.resend_user_verification import (
    ResendUserVerificationUseCase,
)
from link_shortener.application.use_cases.auth.resend_verification import (
    ResendOutcome,
)
from link_shortener.application.use_cases.admin.users.deactivate_user import DeactivateUserUseCase
from link_shortener.application.use_cases.admin.users.delete_user import DeleteUserUseCase
from link_shortener.application.use_cases.admin.users.get_user import GetUserUseCase
from link_shortener.application.use_cases.admin.users.list_user import ListUsersUseCase
from link_shortener.application.use_cases.admin.users.update_user_role import UpdateUserRolesUseCase
from link_shortener.application.use_cases.stats.get_service_health import GetServiceHealthUseCase, ServiceHealthStatus
from link_shortener.application.use_cases.stats.get_user_activity_stats import GetUserActivityStatsUseCase


@dataclass
class AdminService:
    """
    Facade for all administrative operations.

    Aggregates use cases for user and role management as well as service health
    checks and user statistics. The web layer interacts exclusively through this
    class, keeping the internal use case orchestration hidden.

    Attributes:
        create_user_uc: Use case for creating a new user.
        update_user_roles_uc: Use case for updating a user's roles.
        confirm_user_email_uc: Use case for confirming an address on an
            operator's word.
        resend_verification_uc: Use case for sending the confirmation
            message again. Shared with the public endpoint: one way to
            issue a token means one way for it to be retired.
        deactivate_user_uc: Use case for deactivating a user.
        activate_user_uc: Use case for reactivating a user.
        list_users_uc: Use case for listing users.
        get_user_uc: Use case for retrieving a single user.
        delete_user_uc: Use case for deleting a user.
        create_role_uc: Use case for creating a new role.
        update_role_permissions_uc: Use case for updating role permissions.
        delete_role_uc: Use case for deleting a role.
        list_roles_uc: Use case for listing all roles.
        get_role_uc: Use case for retrieving a single role.
        get_service_health_uc: Use case for checking infrastructure health.
        get_user_activity_stats_uc: Use case for obtaining user activity statistics.
    """

    create_user_uc: CreateUserUseCase
    update_user_roles_uc: UpdateUserRolesUseCase
    confirm_user_email_uc: ConfirmUserEmailUseCase
    resend_verification_uc: ResendUserVerificationUseCase
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
    get_service_health_uc: GetServiceHealthUseCase
    get_user_activity_stats_uc: GetUserActivityStatsUseCase

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
        """Create a new user account through the admin panel.

        Args:
            email: User's email address.
            password: Plain-text password.
            context: Request context containing admin's identity.
            role_names: Optional list of role names to assign; if omitted the
                default role is used.
            is_active: Whether the account should be active immediately.

        Returns:
            UserResponse with the newly created user's details.

        Raises:
            DomainError: If the caller is not authorized or validation fails.
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
        """Return a paginated list of all registered users.

        Args:
            context: Request context with admin's identity.
            limit: Maximum number of users to return.
            offset: Number of users to skip.

        Returns:
            List of UserResponse objects.
        """
        return self.list_users_uc.execute(context, limit=limit, offset=offset)

    def get_user(self, user_id: str, context: RequestContext) -> Optional[UserResponse]:
        """Fetch a single user by identifier.

        Args:
            user_id: UUID of the user.
            context: Request context.

        Returns:
            UserResponse if found, otherwise ``None``.
        """
        return self.get_user_uc.execute(user_id, context)

    def get_user_activity_stats(
        self, user_id: str, context: RequestContext
    ) -> "UserActivityResponse":
        """Retrieve activity statistics for a specific user.

        Args:
            user_id: UUID of the user.
            context: Request context. Authorization is *not* handled by
                the use case here, unlike the journal and security-count
                ones: ``GetUserActivityStatsUseCase`` says so itself and
                checks nothing, so the permission is the route's and only
                the route's -- a caller reaching this facade from anywhere
                but a guarded route reads any account's statistics.

        Returns:
            UserActivityResponse containing total links, clicks, and recent links.
        """
        return self.get_user_activity_stats_uc.execute(user_id, context)

    def update_user_roles(
        self, user_id: str, role_names: List[str], context: RequestContext
    ) -> UserResponse:
        """Replace the roles assigned to a user.

        Args:
            user_id: UUID of the user.
            role_names: New list of role names.
            context: Request context with admin's identity.

        Returns:
            Updated UserResponse.
        """
        return self.update_user_roles_uc.execute(
            user_id=user_id, role_names=role_names, context=context
        )

    def deactivate_user(self, user_id: str, context: RequestContext) -> UserResponse:
        """Deactivate a user account (soft delete).

        Args:
            user_id: UUID of the user.
            context: Request context.

        Returns:
            UserResponse with ``is_active`` set to ``False``.
        """
        return self.deactivate_user_uc.execute(user_id, context)

    def confirm_user_email(
        self, user_id: str, context: RequestContext
    ) -> UserResponse:
        """Mark an account's address as confirmed without a mailed link.

        Args:
            user_id: UUID of the account.
            context: Request context carrying the operator's identity.

        Returns:
            UserResponse with ``email_verified`` set to ``True``.
        """
        return self.confirm_user_email_uc.execute(user_id, context)

    def resend_verification(
        self, user_id: str, context: RequestContext
    ) -> Tuple[str, ResendOutcome]:
        """Send the confirmation message again, to a known account.

        Takes an id rather than an address, unlike the public endpoint:
        an operator acts on an account they are looking at, and asking
        them to retype the address invites sending mail to a typo.

        Args:
            user_id: UUID of the account.
            context: Request context.

        Returns:
            The address, and what became of the request. The outcome used
            to be dropped here: this returned the address whatever
            happened, and the route read that as proof of sending, so a
            confirmed account -- for which the use case writes no token
            and queues no message -- was answered ``202 Confirmation
            message sent to ...`` with nothing sent.

        Raises:
            DomainError: With code ``FORBIDDEN`` if the account holds a
                privileged permission the caller does not.
            DomainError: With code ``USER_NOT_FOUND`` when no account
                carries that id.
        """
        return self.resend_verification_uc.execute(user_id, context)

    def activate_user(self, user_id: str, context: RequestContext) -> UserResponse:
        """Reactivate a previously deactivated user account.

        Args:
            user_id: UUID of the user.
            context: Request context.

        Returns:
            UserResponse with ``is_active`` set to ``True``.
        """
        return self.activate_user_uc.execute(user_id, context)

    def delete_user(self, user_id: str, context: RequestContext) -> bool:
        """Permanently delete a user.

        Args:
            user_id: UUID of the user.
            context: Request context.

        Returns:
            ``True`` if the user was deleted, ``False`` if the user did not exist.
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
        """Create a new role with the given permissions.

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
        """Return all roles defined in the system.

        Args:
            context: Request context.

        Returns:
            List of RoleResponse objects.
        """
        return self.list_roles_uc.execute(context)

    def get_role(
        self, role_name: str, context: RequestContext
    ) -> Optional[RoleResponse]:
        """Fetch a single role by name.

        Args:
            role_name: Role name to look up.
            context: Request context.

        Returns:
            RoleResponse if found, otherwise ``None``.
        """
        return self.get_role_uc.execute(role_name, context)

    def update_role_permissions(
        self, role_name: str, permission_names: List[str], context: RequestContext
    ) -> RoleResponse:
        """Replace the permission set of a role.

        Args:
            role_name: Role to update.
            permission_names: New list of permission names (full replacement).
            context: Request context.

        Returns:
            Updated RoleResponse.
        """
        return self.update_role_permissions_uc.execute(
            role_name=role_name,
            permission_names=permission_names,
            context=context,
        )

    def delete_role(self, role_name: str, context: RequestContext) -> None:
        """Delete a non-system role.

        Args:
            role_name: Name of the role to delete.
            context: Request context.

        Raises:
            RoleNotFoundError: If no role carries that name.
            RoleIsSystemError: If the role is one the service owns.

        Neither outcome was ever a return value, though this said they
        were: "``False`` if the role is a system role or not found"
        described a value the use case does not produce.
        """
        self.delete_role_uc.execute(role_name, context)

    # ------------------------------------------------------------------
    # Service health
    # ------------------------------------------------------------------
    def get_service_health(self, context: RequestContext) -> ServiceHealthStatus:
        """Check the health of all infrastructure dependencies.

        Args:
            context: Request context.

        Returns:
            ServiceHealthStatus indicating which components are healthy.
        """
        return self.get_service_health_uc.execute(context)
