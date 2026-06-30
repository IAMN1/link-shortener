from dataclasses import dataclass
from typing import Callable, List

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.user import UserResponse
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.services.user_management_service import UserManagementService
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import DomainError


@dataclass
class UpdateUserRolesUseCase(BaseUseCase):
    """
    Replaces all roles assigned to a user.

    Requires ``admin:manage_users`` permission.
    """

    uow_factory: Callable[[], UnitOfWork]
    user_service: UserManagementService
    logger: Logger

    def execute(
        self,
        user_id: str,
        role_names: List[str],
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

        with self.uow_factory() as uow:
            roles = []
            for name in role_names:
                role = uow.roles.get_by_name(name)
                if not role:
                    raise DomainError(f"Role '{name}' not found", code="VALIDATION_ERROR")
                roles.append(role) 

            updated_user = self.user_service.update_roles(uow, user_id, roles)
            uow.commit()

            log.info("User roles updated", target_user_id=user_id)
            return UserResponse.from_user(updated_user)
