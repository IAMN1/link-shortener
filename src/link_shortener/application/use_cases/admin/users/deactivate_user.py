from dataclasses import dataclass
from typing import Callable

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.user import UserResponse
from link_shortener.application.ports.auth.authorization_service import AuthorizationService
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.services.user_management_service import UserManagementService
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import DomainError


@dataclass
class DeactivateUserUseCase(BaseUseCase):
    """
    Deactivates a user account (they cannot log in).

    Requires ``admin:manage_users`` permission.
    """

    uow_factory: Callable[[], UnitOfWork]
    user_service: UserManagementService
    authorization_service: AuthorizationService
    logger: Logger

    def execute(self, user_id: str, context: RequestContext) -> UserResponse:
        """
        Deactivate a user.

        Args:
            user_id: UUID of the user.
            context: Request context with admin info.

        Returns:
            UserResponse with updated status.

        Raises:
            DomainError: If not authorized.
        """
        log = self._get_logger(self.logger, context)

        with self.uow_factory() as uow:
            admin = None
            if context and context.current_user:
                admin = uow.users.find_by_id(context.current_user.id)
            if not self.authorization_service.is_allowed(admin, "admin:manage_users"):
                log.warning(
                    "Unauthorized attempt to deactivate user",
                    admin_id=admin.id if admin else None
                )
                raise DomainError("Not authorized to manage users", code="FORBIDDEN")

            updated_user = self.user_service.deactivate_user(uow, user_id)
            log.info(
                "User deactivated",
                target_user_id=user_id,
                admin_id=admin.id if admin else None
            )
            return UserResponse.from_user(updated_user)
