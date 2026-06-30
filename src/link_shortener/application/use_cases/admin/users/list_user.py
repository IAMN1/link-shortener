from dataclasses import dataclass
from typing import Callable, List

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.user import UserResponse
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.services.user_management_service import UserManagementService
from link_shortener.application.use_cases.base_use_case import BaseUseCase


@dataclass
class ListUsersUseCase(BaseUseCase):
    """
    Retrieves a paginated list of all users.

    Requires either ``admin:view_users`` or ``admin:manage_users`` permission.
    """

    uow_factory: Callable[[], UnitOfWork]
    user_service: UserManagementService
    logger: Logger

    def execute(
        self,
        context: RequestContext,
        limit: int = 100,
        offset: int = 0,
    ) -> List[UserResponse]:
        """
        Return a list of users.

        Args:
            context: Request context with admin info.
            limit: Maximum number of users to return.
            offset: Number of users to skip.

        Returns:
            List of UserResponse objects.

        Raises:
            DomainError: If the caller lacks permission.
        """
        log = self._get_logger(self.logger, context)

        with self.uow_factory(read_only=True) as uow:

            users = self.user_service.list_users(uow, limit=limit, offset=offset)

            log.info("Retrieve list of users")
            return [UserResponse.from_user(user) for user in users]
