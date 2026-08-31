from dataclasses import dataclass

from link_shortener.application import (
    UnitOfWorkFactory, AuditLogger, CreateRoleUseCase,
    UpdateRolePermissionsUseCase, DeleteRoleUseCase, ListRolesUseCase,
    GetRoleUseCase, RoleManagementService, Logger
)
from link_shortener.application.services.user_management_service import (
    UserManagementService,
)


@dataclass
class AdminRoleUseCasesComponent:
    """
    Provides factory methods for all role administration use cases.

    All dependencies (UoW factory, role service, authorization service,
    logger, audit logger) are injected at construction time.
    """

    uow_factory: UnitOfWorkFactory
    role_service: RoleManagementService
    # Deleting a role puts the accounts it leaves bare back on the default
    # one, and that goes through the same service the other door uses.
    user_service: UserManagementService
    default_role_name: str
    logger: Logger
    audit_logger: AuditLogger

    def get_create_role_use_case(self) -> CreateRoleUseCase:
        """
        Return a configured ``CreateRoleUseCase``.

        Enables creation of a new role with a set of permissions.
        """
        return CreateRoleUseCase(
            uow_factory=self.uow_factory,
            role_service=self.role_service,
            logger=self.logger,
            audit_logger=self.audit_logger,
        )

    def get_update_role_permissions_use_case(self) -> UpdateRolePermissionsUseCase:
        """
        Return a configured ``UpdateRolePermissionsUseCase``.

        Replaces the full permission set of an existing role.
        """
        return UpdateRolePermissionsUseCase(
            uow_factory=self.uow_factory,
            role_service=self.role_service,
            logger=self.logger,
            audit_logger=self.audit_logger,
        )

    def get_delete_role_use_case(self) -> DeleteRoleUseCase:
        """
        Return a configured ``DeleteRoleUseCase``.

        Deletes a non-system role by name.
        """
        return DeleteRoleUseCase(
            uow_factory=self.uow_factory,
            role_service=self.role_service,
            user_service=self.user_service,
            default_role_name=self.default_role_name,
            logger=self.logger,
            audit_logger=self.audit_logger,
        )

    def get_list_roles_use_case(self) -> ListRolesUseCase:
        """
        Return a configured ``ListRolesUseCase``.

        Retrieves all roles in the system.
        """
        return ListRolesUseCase(
            uow_factory=self.uow_factory,
            logger=self.logger,
        )

    def get_get_role_use_case(self) -> GetRoleUseCase:
        """
        Return a configured ``GetRoleUseCase``.

        Fetches a single role by name.
        """
        return GetRoleUseCase(
            uow_factory=self.uow_factory,
            logger=self.logger,
        )
