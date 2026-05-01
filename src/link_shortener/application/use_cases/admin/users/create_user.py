from dataclasses import dataclass
from typing import Callable, List, Optional

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.user import UserResponse
from link_shortener.application.ports.auth.authorization_service import AuthorizationService
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.services.user_management_service import UserManagementService
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import Role, DomainError


@dataclass
class CreateUserUseCase(BaseUseCase):
    """
    Creates a new user account with optional custom roles.

    Requires the ``admin:manage_users`` permission.
    """

    uow_factory: Callable[[], UnitOfWork]
    user_service: UserManagementService
    authorization_service: AuthorizationService
    logger: Logger

    def execute(
            self,
            email: str,
            password: str,
            context: RequestContext,
            roles: Optional[List[Role]] = None,
            is_active: bool = True,
    ) -> UserResponse:
        """
        Create a new user.

        Args:
            email: Email address.
            password: Plain-text password.
            context: Request context with admin info.
            roles: Specific roles to assign; if None, the default role is used.
            is_active: Whether the account is active at creation.

        Returns:
            UserResponse for the newly created user.

        Raises:
            DomainError: If the admin is not authorized or a business rule is violated.
        """
        log = self._get_logger(self.logger, context)

        with self.uow_factory() as uow:
            admin = None
            if context and context.current_user:
                admin = uow.users.find_by_id(context.current_user.id)
            if not self.authorization_service.is_allowed(admin, "admin:manage_users"):
                log.warning(
                    "Unauthorized attempt to create user",
                    admin_id=admin.id if admin else None
                )
                raise DomainError("Not authorized to manage users", code="FORBIDDEN")
        
            try:
                new_user = self.user_service.create_user(
                    uow=uow,
                    email=email,
                    password=password,
                    roles=roles,
                    is_active=is_active,
                )
                uow.commit()

                log.info(
                    "User created by admin",
                    new_user_id=new_user.id,
                    admin_id=admin.id if admin else None
                )
                return UserResponse.from_user(new_user)
            except Exception as e:
                log.error("User creation failed", error=str(e))
                raise
