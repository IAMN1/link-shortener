from dataclasses import dataclass
from typing import Callable, List

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.user import UserResponse
from link_shortener.application.ports.auth.authorization_service import AuthorizationService
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.services.user_management_service import UserManagementService
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import Role, DomainError


@dataclass
class UpdateUserRolesUseCase(BaseUseCase):
    """
    Replaces all roles assigned to a user.

    Requires ``admin:manage_users`` permission.
    """

    uow_factory: Callable[[], UnitOfWork]
    user_service: UserManagementService
    authorization_service: AuthorizationService
    logger: Logger

    def execute(
        self,
        user_id: str,
        roles: List[Role],
        context: RequestContext,
    ) -> UserResponse:
        """
        Update user roles.

        Args:
            user_id: UUID of the target user.
            roles: New list of domain Role entities to assign.
            context: Request context with admin info.

        Returns:
            UserResponse reflecting the new roles.

        Raises:
            DomainError: If the caller is not authorized.
        """
        log = self._get_logger(self.logger, context)

        admin = context.current_user if context else None
        with self.uow_factory() as uow:
            if not self.authorization_service.is_allowed(admin, "admin:manage_users"):
                log.warning(
                    "Unauthorized attempt to update user roles",
                    admin_id=admin.id if admin else None
                )
                raise DomainError("Not authorized to manage users", code="FORBIDDEN")

            updated_user = self.user_service.update_roles(uow, user_id, roles)
            uow.commit()

            log.info(
                "User roles updated",
                target_user_id=user_id,
                admin_id=admin.id if admin else None
            )
            return UserResponse.from_user(updated_user)
