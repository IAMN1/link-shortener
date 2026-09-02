from dataclasses import dataclass
from typing import List

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.user import UserResponse
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.services.user_management_service import UserManagementService
from link_shortener.application.use_cases.base_use_case import BaseUseCase


@dataclass
class ListUsersUseCase(BaseUseCase):
    """
    Retrieves a paginated list of all users.

    Requires ``admin:view_users``. Not "either that or ``admin:manage_users``", which is what
    this said: the routes ask for one named permission each, and
    ``test_each_admin_route_asks_for_its_own_permission`` holds them to
    it -- OWASP A01 asks a system to deny by default, and an account
    built to manage is not thereby an account built to read.
    """

    uow_factory: UnitOfWorkFactory
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
