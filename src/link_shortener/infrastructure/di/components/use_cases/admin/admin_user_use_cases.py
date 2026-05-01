from dataclasses import dataclass
from typing import Callable

from link_shortener.application import (
    CreateUserUseCase,
    UpdateUserRolesUseCase,
    DeactivateUserUseCase,
    ActivateUserUseCase,
    ListUsersUseCase,
    GetUserUseCase,
    DeleteUserUseCase,
    UserManagementService,
    AuthorizationService,
    Logger,
    UnitOfWork,
)


@dataclass
class AdminUserUseCasesComponent:
    """
    Holds dependencies for user administration use cases.

    All methods return fully initialised use case instances.
    """

    uow_factory: Callable[[], UnitOfWork]
    user_service: UserManagementService
    authorization_service: AuthorizationService
    logger: Logger

    def get_create_user_use_case(self) -> CreateUserUseCase:
        """Return a configured ``CreateUserUseCase``."""
        return CreateUserUseCase(
            user_service=self.user_service,
            authorization_service=self.authorization_service,
            logger=self.logger,
            uow_factory=self.uow_factory,
        )

    def get_update_user_roles_use_case(self) -> UpdateUserRolesUseCase:
        """Return a configured ``UpdateUserRolesUseCase``."""
        return UpdateUserRolesUseCase(
            user_service=self.user_service,
            authorization_service=self.authorization_service,
            logger=self.logger,
            uow_factory=self.uow_factory,
        )

    def get_deactivate_user_use_case(self) -> DeactivateUserUseCase:
        """Return a configured ``DeactivateUserUseCase``."""
        return DeactivateUserUseCase(
            user_service=self.user_service,
            authorization_service=self.authorization_service,
            logger=self.logger,
            uow_factory=self.uow_factory,
        )

    def get_activate_user_use_case(self) -> ActivateUserUseCase:
        """Return a configured ``ActivateUserUseCase``."""
        return ActivateUserUseCase(
            user_service=self.user_service,
            authorization_service=self.authorization_service,
            logger=self.logger,
            uow_factory=self.uow_factory,
        )

    def get_list_users_use_case(self) -> ListUsersUseCase:
        """Return a configured ``ListUsersUseCase``."""
        return ListUsersUseCase(
            user_service=self.user_service,
            authorization_service=self.authorization_service,
            logger=self.logger,
            uow_factory=self.uow_factory,
        )

    def get_get_user_use_case(self) -> GetUserUseCase:
        """Return a configured ``GetUserUseCase``."""
        return GetUserUseCase(
            user_service=self.user_service,
            authorization_service=self.authorization_service,
            logger=self.logger,
            uow_factory=self.uow_factory,
        )

    def get_delete_user_use_case(self) -> DeleteUserUseCase:
        """Return a configured ``DeleteUserUseCase``."""
        return DeleteUserUseCase(
            user_service=self.user_service,
            authorization_service=self.authorization_service,
            logger=self.logger,
            uow_factory=self.uow_factory,
        )
