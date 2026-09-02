from dataclasses import dataclass

from link_shortener.application import (
    UnitOfWorkFactory, CreateUserUseCase,
    UpdateUserRolesUseCase, DeactivateUserUseCase, ActivateUserUseCase,
    ListUsersUseCase, GetUserUseCase, DeleteUserUseCase,
    ConfirmUserEmailUseCase,
    UserManagementService, AuditLogger, LinkCache, Logger, RedirectCache,
    StatsCache
)


@dataclass
class AdminUserUseCasesComponent:
    """
    Holds dependencies for user administration use cases.

    All methods return fully initialised use case instances.
    """

    uow_factory: UnitOfWorkFactory
    user_service: UserManagementService
    cache: LinkCache
    redirect_cache: RedirectCache
    stats_cache: StatsCache
    logger: Logger
    audit_logger: AuditLogger

    def get_create_user_use_case(self) -> CreateUserUseCase:
        """Return a configured ``CreateUserUseCase``."""
        return CreateUserUseCase(
            user_service=self.user_service,
            logger=self.logger,
            uow_factory=self.uow_factory,
            audit_logger=self.audit_logger,
        )

    def get_update_user_roles_use_case(self) -> UpdateUserRolesUseCase:
        """Return a configured ``UpdateUserRolesUseCase``."""
        return UpdateUserRolesUseCase(
            user_service=self.user_service,
            logger=self.logger,
            uow_factory=self.uow_factory,
            audit_logger=self.audit_logger,
        )

    def get_deactivate_user_use_case(self) -> DeactivateUserUseCase:
        """Return a configured ``DeactivateUserUseCase``."""
        return DeactivateUserUseCase(
            user_service=self.user_service,
            logger=self.logger,
            uow_factory=self.uow_factory,
            audit_logger=self.audit_logger,
        )

    def get_confirm_user_email_use_case(self) -> ConfirmUserEmailUseCase:
        """Return a configured ``ConfirmUserEmailUseCase``."""
        return ConfirmUserEmailUseCase(
            logger=self.logger,
            uow_factory=self.uow_factory,
            audit_logger=self.audit_logger,
        )

    def get_activate_user_use_case(self) -> ActivateUserUseCase:
        """Return a configured ``ActivateUserUseCase``."""
        return ActivateUserUseCase(
            user_service=self.user_service,
            logger=self.logger,
            uow_factory=self.uow_factory,
            audit_logger=self.audit_logger,
        )

    def get_list_users_use_case(self) -> ListUsersUseCase:
        """Return a configured ``ListUsersUseCase``."""
        return ListUsersUseCase(
            user_service=self.user_service,
            logger=self.logger,
            uow_factory=self.uow_factory,
        )

    def get_get_user_use_case(self) -> GetUserUseCase:
        """Return a configured ``GetUserUseCase``."""
        return GetUserUseCase(
            user_service=self.user_service,
            logger=self.logger,
            uow_factory=self.uow_factory,
        )

    def get_delete_user_use_case(self) -> DeleteUserUseCase:
        """Return a configured ``DeleteUserUseCase``."""
        return DeleteUserUseCase(
            user_service=self.user_service,
            cache=self.cache,
            redirect_cache=self.redirect_cache,
            stats_cache=self.stats_cache,
            logger=self.logger,
            audit_logger=self.audit_logger,
            uow_factory=self.uow_factory,
        )
