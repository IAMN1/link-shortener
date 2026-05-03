from dataclasses import dataclass
from typing import Callable, List

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.user import UserResponse
from link_shortener.application.ports.auth.authorization_service import AuthorizationService
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.services.user_management_service import UserManagementService
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import DomainError, SystemPermissions


@dataclass
class ListUsersUseCase(BaseUseCase):
    """
    Retrieves a paginated list of all users.

    Requires either ``admin:view_users`` or ``admin:manage_users`` permission.
    """

    uow_factory: Callable[[], UnitOfWork]
    user_service: UserManagementService
    authorization_service: AuthorizationService
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
            admin = None
            if context and context.current_user:
                admin = uow.users.find_by_id(context.current_user.id)
            if (
                not self.authorization_service.is_allowed(admin, SystemPermissions.ADMIN_MANAGE_USERS.value) 
                and not self.authorization_service.is_allowed(admin, SystemPermissions.ADMIN_VIEW_USERS.value)
            ):
                log.warning(
                    "Unauthorized attempt to list users",
                    admin_id=admin.id if admin else None
                )
                raise DomainError("Not authorized to view users", code="FORBIDDEN")

            users = self.user_service.list_users(uow, limit=limit, offset=offset)
            return [UserResponse.from_user(user) for user in users]
