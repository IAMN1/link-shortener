from dataclasses import dataclass
from typing import Callable, List

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.admin.role import RoleResponse
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.services.role_management_service import RoleManagementService
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import DomainError


@dataclass
class UpdateRolePermissionsUseCase(BaseUseCase):
    """
    Replaces the entire permission set of a non-system role.

    Requires ``admin:manage_roles`` permission.
    """
    uow_factory: Callable[[], UnitOfWork]
    role_service: RoleManagementService
    logger: Logger

    def execute(
            self,
            role_name: str,
            permission_names: List[str],
            context: RequestContext
    ) -> RoleResponse:
        """
        Update permissions.

        Args:
            role_name: Unique role name.
            permission_names: New list of permission names (full replacement).
            context: Request context with current user info.

        Returns:
            RoleResponse reflecting the updated role.

        Raises:
            DomainError: If the user is not authorized or the role update fails.
        """
        log = self._get_logger(self.logger, context)

        with self.uow_factory() as uow:
            try:
                role = self.role_service.update_role_permissions(uow, role_name, permission_names)
                uow.commit()
                
                log.info("Role updated", role_name=role.name)
                return RoleResponse.from_role(role)
            except ValueError as e:
                log.error("Role update failed", error=str(e))
                raise DomainError(str(e), code="ROLE_UPDATE_FAILED")
