from dataclasses import dataclass
from typing import Callable, List

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.admin.role import RoleResponse
from link_shortener.application.ports.auth.authorization_service import AuthorizationService
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import DomainError, SystemPermissions


@dataclass
class ListRolesUseCase(BaseUseCase):
    """
    Retrieves all roles defined in the system.

    Requires either ``admin:view_roles`` or ``admin:manage_roles`` permission.
    """
    uow_factory: Callable[[], UnitOfWork]
    authorization_service: AuthorizationService
    logger: Logger

    def execute(self, context: RequestContext) -> List[RoleResponse]:
        """
        Return all roles.

        Args:
            context: Request context with current user info.

        Returns:
            List of RoleResponse objects.

        Raises:
            DomainError: If the user is not authorized.
        """
        log = self._get_logger(self.logger, context)

        user = context.current_user
        with self.uow_factory(read_only=True) as uow:
            if (
                not self.authorization_service.is_allowed(user, SystemPermissions.ADMIN_MANAGE_ROLES.value) 
                and not self.authorization_service.is_allowed(user, SystemPermissions.ADMIN_VIEW_ROLES.value)
            ):
                log.warning(
                    "Unauthorized attempt to list roles",
                    user_id=user.id if user else None
                )
                raise DomainError("Not authorized to view roles", code="FORBIDDEN")
            roles = uow.roles.list_all()
            return [RoleResponse.from_role(role) for role in roles]
