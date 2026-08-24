from dataclasses import dataclass
from typing import List

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.admin.role import RoleResponse
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.services.role_management_service import RoleManagementService
from link_shortener.application.use_cases.admin.privilege_guard import (
    require_administrator_survives_without,
    require_may_grant_permissions,
)
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import SystemPermissions


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
            RoleNotFoundError: If there is no role under that name,
                answered 404 -- the same answer `delete_role` gives the
                same question.
            RoleIsSystemError: If the role is one the service owns.
            PermissionsNotFoundError: If a named permission does not exist.
            DomainError: With code ``FORBIDDEN`` when the new set would
                leave the system without an administrator.
            DomainError: If the caller may not confer what they asked for.
        """
        log = self._get_logger(self.logger, context)
        audit = self._get_audit_logger(self.audit_logger, context)

        with self.uow_factory() as uow:
            # See CreateRoleUseCase: the request is checked before the
            # caller, so a mistyped permission is answered as one.
            self.role_service.resolve_permissions(uow, permission_names)

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
            # How far this reaches. Replacing what a role grants moves
            # every account wearing it, at once and without any of them
            # being touched, so the count is the only thing in the record
            # that says whether that was one account or all of them.
            holders = uow.users.count_with_role(existing.id) if existing else 0

            # Replacing what a role carries can take ``admin:all`` off the
            # last administrator just as deleting the role would, and the
            # rule stood on neither route. Asked only when the new set
            # actually drops it: a replacement that keeps it changes
            # nothing about who is an administrator.
            # A system role is refused whatever the count says, so it is
            # left to the service: see `delete_role` for what asking in
            # the other order did to one request's answer.
            if (
                existing is not None
                and not existing.is_system
                and SystemPermissions.ADMIN_ALL.value not in permission_names
            ):
                require_administrator_survives_without(uow, existing)

            # Raised by the service and left alone, for the reason written
            # in `create_role`: a generic ``ROLE_UPDATE_FAILED`` answered
            # 400 to a role that is simply not there, while the delete
            # route beside it answered 404 to the very same question.
            role = self.role_service.update_role_permissions(
                uow, role_name, permission_names
            )
            uow.commit()

        permissions_after = [p.name for p in role.permissions]
        # See ``UpdateUserRolesUseCase``: only a real change is recorded,
        # and the comparison ignores the order the request happened to
        # list them in.
        changed = sorted(permissions_before) != sorted(permissions_after)

        log.info(
            "Role updated", role_name=role.name, holders=holders,
            changed=changed,
        )
        if changed:
            audit.log_role_permissions_changed(
                role=role.name,
                permissions_before=permissions_before,
                permissions_after=permissions_after,
                holders=holders,
            )
        return RoleResponse.from_role(role)
