from dataclasses import dataclass
from typing import Optional

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.admin.role import RoleResponse
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.use_cases.base_use_case import BaseUseCase


@dataclass
class GetRoleUseCase(BaseUseCase):
    """
    Retrieves a single role by its unique name.

    Requires ``admin:view_roles``. Not "either that or ``admin:manage_roles``", which is what
    this said: the routes ask for one named permission each, and
    ``test_each_admin_route_asks_for_its_own_permission`` holds them to
    it -- OWASP A01 asks a system to deny by default, and an account
    built to manage is not thereby an account built to read.
    """

    uow_factory: UnitOfWorkFactory
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
