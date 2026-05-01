from dataclasses import dataclass
from typing import Callable, Optional

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.user import UserResponse
from link_shortener.application.ports.auth.authorization_service import AuthorizationService
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.services.user_management_service import UserManagementService
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import DomainError


@dataclass
class GetUserUseCase(BaseUseCase):
    """
    Retrieves a single user by their identifier.

    Requires either ``admin:view_users`` or ``admin:manage_users`` permission.
    """

    uow_factory: Callable[[], UnitOfWork]
    user_service: UserManagementService
    authorization_service: AuthorizationService
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
            admin = None
            if context and context.current_user:
                admin = uow.users.find_by_id(context.current_user.id)
            
            # Permission check: view_users or manage_users
            if (
                not self.authorization_service.is_allowed(admin, "admin:manage_users") 
                and not self.authorization_service.is_allowed(admin, "admin:view_users")
            ):
                log.warning(
                    "Unauthorized attempt to view user",
                    admin_id=admin.id if admin else None
                )
                raise DomainError("Not authorized to view users", code="FORBIDDEN")
            
            user = self.user_service.get_user_by_id(uow, user_id)
            return UserResponse.from_user(user) if user else None
