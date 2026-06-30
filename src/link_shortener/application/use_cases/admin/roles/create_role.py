from dataclasses import dataclass
from typing import Callable, List, Optional

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.admin.role import RoleResponse
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.services.role_management_service import RoleManagementService
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import DomainError


@dataclass
class CreateRoleUseCase(BaseUseCase):
    """
    Creates a new role with a list of permissions.

    Requires the caller to hold the ``admin:manage_roles`` permission.
    """

    uow_factory: Callable[[], UnitOfWork]
    role_service: RoleManagementService
    logger: Logger

    def execute(
            self,
            name: str,
            description: Optional[str],
            permission_names: List[str],
            context: RequestContext
    ) -> RoleResponse:
        """
        Execute the use case.

        Args:
            name: Unique role name.
            description: Optional description.
            permission_names: Permission names to assign.
            context: Request context with current user info.

        Returns:
            RoleResponse for the created role.

        Raises:
            DomainError: If the user is not authorized or a domain rule is violated.
        """
        log = self._get_logger(self.logger, context)

        with self.uow_factory() as uow:
            try:
                role = self.role_service.create_role(
                    uow=uow,
                    name=name,
                    description=description,
                    permission_names=permission_names,
                )
                uow.commit()

                log.info("Role created successfully", role_name=role.name)
                return RoleResponse.from_role(role)
            except ValueError as e:
                log.error("Role creation failed", error=str(e))
                raise DomainError(str(e), code="ROLE_CREATION_FAILED")
