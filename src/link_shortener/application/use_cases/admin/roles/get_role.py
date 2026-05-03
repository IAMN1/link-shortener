from dataclasses import dataclass
from typing import Callable, Optional

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.admin.role import RoleResponse
from link_shortener.application.ports.auth.authorization_service import AuthorizationService
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import DomainError, SystemPermissions


@dataclass
class GetRoleUseCase(BaseUseCase):
    """
    Retrieves a single role by its unique name.

    Requires either ``admin:view_roles`` or ``admin:manage_roles`` permission.
    """

    uow_factory: Callable[[], UnitOfWork]
    authorization_service: AuthorizationService
    logger: Logger

    def execute(self, role_name: str, context: RequestContext) -> Optional[RoleResponse]:
        """
        Fetch the role.

        Args:
            role_name: Role name to look up.
            context: Request context with current user info.

        Returns:
            RoleResponse if found, else ``None``.

        Raises:
            DomainError: If the user is not authorized to view roles.
        """
        log = self._get_logger(self.logger, context)

        user = context.current_user
        with self.uow_factory(read_only=True) as uow:
            # Permission check: view_roles OR manage_roles
            if (
                not self.authorization_service.is_allowed(user, SystemPermissions.ADMIN_MANAGE_ROLES.value) 
                and not self.authorization_service.is_allowed(user, SystemPermissions.ADMIN_VIEW_ROLES.value)
            ):
                log.warning(
                    "Unauthorized attempt to view role", 
                    user_id=user.id if user else None
                )
                raise DomainError("Not authorized to view roles", code="FORBIDDEN")
            role = uow.roles.get_by_name(role_name)
            return RoleResponse.from_role(role) if role else None
