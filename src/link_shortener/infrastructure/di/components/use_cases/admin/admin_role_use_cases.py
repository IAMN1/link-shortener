from dataclasses import dataclass
from typing import Callable

from link_shortener.application import (
    CreateRoleUseCase,
    UpdateRolePermissionsUseCase,
    DeleteRoleUseCase,
    ListRolesUseCase,
    GetRoleUseCase,
    RoleManagementService,
    AuthorizationService,
    Logger,
    UnitOfWork,
)


@dataclass
class AdminRoleUseCasesComponent:
    """
    Provides factory methods for all role administration use cases.

    All dependencies (UoW factory, role service, authorization service,
    logger) are injected at construction time.
    """

    uow_factory: Callable[[], UnitOfWork]
    role_service: RoleManagementService
    authorization_service: AuthorizationService
    logger: Logger

    def get_create_role_use_case(self) -> CreateRoleUseCase:
        """
        Return a configured ``CreateRoleUseCase``.

        Enables creation of a new role with a set of permissions.
        """
        return CreateRoleUseCase(
            uow_factory=self.uow_factory,
            role_service=self.role_service,
            authorization_service=self.authorization_service,
            logger=self.logger,
        )

    def get_update_role_permissions_use_case(self) -> UpdateRolePermissionsUseCase:
        """
        Return a configured ``UpdateRolePermissionsUseCase``.

        Replaces the full permission set of an existing role.
        """
        return UpdateRolePermissionsUseCase(
            uow_factory=self.uow_factory,
            role_service=self.role_service,
            authorization_service=self.authorization_service,
            logger=self.logger,
        )

    def get_delete_role_use_case(self) -> DeleteRoleUseCase:
        """
        Return a configured ``DeleteRoleUseCase``.

        Deletes a non-system role by name.
        """
        return DeleteRoleUseCase(
            uow_factory=self.uow_factory,
            role_service=self.role_service,
            authorization_service=self.authorization_service,
            logger=self.logger,
        )

    def get_list_roles_use_case(self) -> ListRolesUseCase:
        """
        Return a configured ``ListRolesUseCase``.

        Retrieves all roles in the system.
        """
        return ListRolesUseCase(
            uow_factory=self.uow_factory,
            authorization_service=self.authorization_service,
            logger=self.logger,
        )

    def get_get_role_use_case(self) -> GetRoleUseCase:
        """
        Return a configured ``GetRoleUseCase``.

        Fetches a single role by name.
        """
        return GetRoleUseCase(
            uow_factory=self.uow_factory,
            authorization_service=self.authorization_service,
            logger=self.logger,
        )
