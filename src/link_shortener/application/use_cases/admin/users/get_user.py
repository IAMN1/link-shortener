from dataclasses import dataclass
from typing import Optional

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.user import UserResponse
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.services.user_management_service import UserManagementService
from link_shortener.application.use_cases.base_use_case import BaseUseCase


@dataclass
class GetUserUseCase(BaseUseCase):
    """
    Retrieves a single user by their identifier.

    Requires ``admin:view_users``. Not "either that or ``admin:manage_users``", which is what
    this said: the routes ask for one named permission each, and
    ``test_each_admin_route_asks_for_its_own_permission`` holds them to
    it -- OWASP A01 asks a system to deny by default, and an account
    built to manage is not thereby an account built to read.
    """

    uow_factory: UnitOfWorkFactory
    user_service: UserManagementService
    logger: Logger

    def execute(self, user_id: str, context: RequestContext) -> Optional[UserResponse]:
        """
        Look up a user.

        Args:
            user_id: UUID of the user.
            context: Request context with admin info.

        Returns:
            UserResponse if found, else ``None``.

        Raises:
            DomainError: If the caller lacks permission.
        """
        log = self._get_logger(self.logger, context)

        with self.uow_factory(read_only=True) as uow:
            user = self.user_service.get_user_by_id(uow, user_id)

            if user:
                log.info("Get user successfully", user_id=user.id)
            return UserResponse.from_user(user) if user else None
