from dataclasses import dataclass
from typing import Callable

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.services.user_management_service import UserManagementService
from link_shortener.application.use_cases.base_use_case import BaseUseCase


@dataclass
class DeleteUserUseCase(BaseUseCase):
    """
    Permanently removes a user from the system.

    Requires ``admin:manage_users`` permission.
    """

    uow_factory: Callable[[], UnitOfWork]
    user_service: UserManagementService
    logger: Logger

    def execute(self, user_id: str, context: RequestContext) -> bool:
        """
        Delete a user.

        Args:
            user_id: UUID of the user to delete.
            context: Request context with admin info.

        Returns:
            ``True`` if the user was deleted, ``False`` if the user was not found.

        Raises:
            DomainError: If the caller is not authorized.
        """
        log = self._get_logger(self.logger, context)

        with self.uow_factory() as uow:
            deleted = self.user_service.delete_user(uow, user_id)
            if deleted:
                uow.commit()
                log.info("User deleted", target_user_id=user_id)
            return deleted
