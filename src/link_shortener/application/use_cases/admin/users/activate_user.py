from dataclasses import dataclass
from typing import Callable

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.user import UserResponse
from link_shortener.application.ports.auth.authorization_service import AuthorizationService
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.services.user_management_service import UserManagementService
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import DomainError, SystemPermissions


@dataclass
class ActivateUserUseCase(BaseUseCase):
    """
    Reactivates a user account.

    Requires the ``admin:manage_users`` permission.
    """

    uow_factory: Callable[[], UnitOfWork]
    user_service: UserManagementService
    authorization_service: AuthorizationService
    logger: Logger

    def execute(self, user_id: str, context: RequestContext) -> UserResponse:
        """
        Activate a user.

        Args:
            user_id: UUID of the user to activate.
            context: Request context with current admin info.

        Returns:
            UserResponse with updated status.

        Raises:
            DomainError: If the caller is not authorized or the user does not exist.
        """
        log = self._get_logger(self.logger, context)

        with self.uow_factory() as uow:
            # Identify admin
            admin = None
            if context and context.current_user:
                admin = uow.users.find_by_id(context.current_user.id)

            # Authorization: only users with admin:manage_users may activate
            if not self.authorization_service.is_allowed(admin, SystemPermissions.ADMIN_MANAGE_USERS.value):
                log.warning(
                    "Unauthorized attempt to activate user",
                    admin_id=admin.id if admin else None
                )
                raise DomainError("Not authorized to manage users", code="FORBIDDEN")

            updated_user = self.user_service.activate_user(uow, user_id)
            log.info(
                "User activated",
                target_user_id=user_id,
                admin_id=admin.id if admin else None
            )
            return UserResponse.from_user(updated_user)
