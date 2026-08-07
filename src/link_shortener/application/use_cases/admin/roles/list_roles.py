from dataclasses import dataclass
from typing import Callable, List

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.admin.role import RoleResponse
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.use_cases.base_use_case import BaseUseCase

@dataclass
class ListRolesUseCase(BaseUseCase):
    """
    Retrieves all roles defined in the system.

    Requires either ``admin:view_roles`` or ``admin:manage_roles`` permission.
    """
    uow_factory: Callable[[], UnitOfWork]
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

        with self.uow_factory(read_only=True) as uow:
            roles = uow.roles.list_all()

            log.info("Roles list retrieve successfully")
            return [RoleResponse.from_role(role) for role in roles]
