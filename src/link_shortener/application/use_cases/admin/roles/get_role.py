from dataclasses import dataclass
from typing import Callable, Optional

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.admin.role import RoleResponse
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.use_cases.base_use_case import BaseUseCase


@dataclass
class GetRoleUseCase(BaseUseCase):
    """
    Retrieves a single role by its unique name.

    Requires either ``admin:view_roles`` or ``admin:manage_roles`` permission.
    """

    uow_factory: Callable[[], UnitOfWork]
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

        with self.uow_factory(read_only=True) as uow:
            role = uow.roles.get_by_name(role_name)

            log.info("Role retrieve successfully")
            return RoleResponse.from_role(role) if role else None
