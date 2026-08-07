from dataclasses import dataclass
from typing import Callable

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.user import UserResponse
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.services.user_management_service import UserManagementService
from link_shortener.application.use_cases.base_use_case import BaseUseCase


@dataclass
class ActivateUserUseCase(BaseUseCase):
    """
    Reactivates a user account.

    Requires the ``admin:manage_users`` permission.
    """

    uow_factory: Callable[[], UnitOfWork]
    user_service: UserManagementService
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
            updated_user = self.user_service.activate_user(uow, user_id)
            uow.commit()

            log.info("User activated", target_user_id=user_id)
            return UserResponse.from_user(updated_user)
