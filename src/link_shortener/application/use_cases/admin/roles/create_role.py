from dataclasses import dataclass
from typing import List, Optional

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.admin.role import RoleResponse
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.services.role_management_service import RoleManagementService
from link_shortener.application.use_cases.admin.privilege_guard import (
    require_may_grant_permissions,
)
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import DomainError


@dataclass
class CreateRoleUseCase(BaseUseCase):
    """
    Creates a new role with a list of permissions.

    Requires the caller to hold the ``admin:manage_roles`` permission.

    Attributes:
        uow_factory: Callable factory for creating Unit of Work instances.
        role_service: Service that creates the role itself.
        logger: Application logger.
        audit_logger: Audit logger, where the role and what it grants are
            recorded.
    """

    uow_factory: UnitOfWorkFactory
    role_service: RoleManagementService
    logger: Logger
    audit_logger: AuditLogger

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
            DomainError: If the user is not authorized, if a requested
                permission exceeds what the caller holds, or if a domain
                rule is violated.
        """
        log = self._get_logger(self.logger, context)
        audit = self._get_audit_logger(self.audit_logger, context)

        with self.uow_factory() as uow:
            # A role is a bundle of permissions, and handing one out is
            # handing them out. Without this, ``admin:manage_roles`` was a
            # two-step spelling of ``admin:all``: put the permission in a
            # role you already wear, then read it back.
            require_may_grant_permissions(context, uow, permission_names)

            try:
                role = self.role_service.create_role(
                    uow=uow,
                    name=name,
                    description=description,
                    permission_names=permission_names,
                )
                uow.commit()

                log.info("Role created successfully", role_name=role.name)
                # The permissions as the role ended up holding them, not as
                # they were asked for: a name the service did not resolve
                # is not a permission this role grants, and recording the
                # request would overstate what was created.
                audit.log_role_created(
                    role=role.name,
                    permissions=[p.name for p in role.permissions],
                )
                return RoleResponse.from_role(role)
            except ValueError as e:
                log.error("Role creation failed", error=str(e))
                raise DomainError(str(e), code="ROLE_CREATION_FAILED")
