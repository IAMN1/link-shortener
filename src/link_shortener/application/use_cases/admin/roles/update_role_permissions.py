from dataclasses import dataclass
from typing import List

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
class UpdateRolePermissionsUseCase(BaseUseCase):
    """
    Replaces the entire permission set of a non-system role.

    Requires ``admin:manage_roles`` permission.

    Attributes:
        uow_factory: Callable factory for creating Unit of Work instances.
        role_service: Service that writes the new permission set.
        logger: Application logger.
        audit_logger: Audit logger. This is the widest-reaching change the
            administrative surface allows -- it moves what every holder of
            the role may do, without touching a single account -- so both
            sides of it are recorded.
    """
    uow_factory: UnitOfWorkFactory
    role_service: RoleManagementService
    logger: Logger
    audit_logger: AuditLogger

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
            DomainError: If the user is not authorized, if a requested
                permission exceeds what the caller holds, or if the role
                update fails.
        """
        log = self._get_logger(self.logger, context)
        audit = self._get_audit_logger(self.audit_logger, context)

        with self.uow_factory() as uow:
            # See CreateRoleUseCase: widening a role the caller wears is
            # the same escalation by another route.
            require_may_grant_permissions(context, uow, permission_names)

            # Read before the replacement, which is what makes the record
            # answer "what did this role use to grant" -- the question an
            # investigator arrives with, and the one the new set alone
            # cannot answer.
            existing = uow.roles.get_by_name(role_name)
            permissions_before = (
                [p.name for p in existing.permissions] if existing else []
            )

            try:
                role = self.role_service.update_role_permissions(uow, role_name, permission_names)
                uow.commit()

                log.info("Role updated", role_name=role.name)
                audit.log_role_permissions_changed(
                    role=role.name,
                    permissions_before=permissions_before,
                    permissions_after=[p.name for p in role.permissions],
                )
                return RoleResponse.from_role(role)
            except ValueError as e:
                log.error("Role update failed", error=str(e))
                raise DomainError(str(e), code="ROLE_UPDATE_FAILED")
