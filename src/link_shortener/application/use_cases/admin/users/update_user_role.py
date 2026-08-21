from dataclasses import dataclass
from typing import List

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.user import UserResponse
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.services.role_management_service import RoleManagementService
from link_shortener.application.services.user_management_service import UserManagementService
from link_shortener.application.use_cases.admin.privilege_guard import (
    is_administrator,
    require_administrator_remains,
    require_may_grant_roles,
    would_keep_admin,
)
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain.policies.role_policy import (
    require_roles_are_assignable,
)


@dataclass
class UpdateUserRolesUseCase(BaseUseCase):
    """
    Replaces all roles assigned to a user.

    Requires ``admin:manage_users`` permission.

    Attributes:
        uow_factory: Callable factory for creating Unit of Work instances.
        user_service: Service that writes the new set of roles.
        logger: Application logger.
        audit_logger: Audit logger, where both sides of the change go.
    """

    uow_factory: UnitOfWorkFactory
    user_service: UserManagementService
    logger: Logger
    audit_logger: AuditLogger

    def execute(
        self,
        user_id: str,
        role_names: List[str],
        context: RequestContext,
    ) -> UserResponse:
        """
        Update user roles.

        Args:
            user_id: UUID of the target user.
            roles: New list of domain Role entities to assign.
            context: Request context with admin info.

        Returns:
            UserResponse reflecting the new roles.

        Raises:
            RoleNotAssignableError: If a named role is one no account may
                wear, answered 400.
            RoleNotFoundError: If a named role does not exist, answered
                404 -- the answer the role endpoints give that question.
            DomainError: If the caller is not authorized, if a role carries
                a permission the caller does not hold, or if the change
                would leave the system without an administrator.
        """
        log = self._get_logger(self.logger, context)
        audit = self._get_audit_logger(self.audit_logger, context)

        with self.uow_factory() as uow:
            # Resolved by the service rather than here: a name nothing
            # carries used to be a ``VALIDATION_ERROR``, answered 400,
            # while the role endpoints answered 404 to the same question.
            roles = RoleManagementService.resolve_roles(uow, role_names)

            # What is wrong with the request, before what is wrong with
            # the state. ``UserManagementService.update_roles`` asks this
            # too and stays the door every path goes through -- but it
            # asks after the administrator count, so ``{"roles":
            # ["guest"]}`` aimed at the last administrator came back
            # "this would leave the system without an administrator".
            # That reads as "find another administrator and retry", and
            # the request would be refused just the same: no account may
            # wear ``guest``, whatever the count says.
            require_roles_are_assignable(roles)

            # ``admin:manage_users`` is not a shorter spelling of
            # ``admin:all``: assign yourself the admin role, read the
            # permissions back. Nothing asked whether the caller was
            # entitled to what they were handing out.
            require_may_grant_roles(context, uow, roles)

            # Asked in the same transaction that will write the change, and
            # only when it actually takes the permission away.
            if is_administrator(uow, user_id) and not would_keep_admin(roles):
                require_administrator_remains(uow, user_id)

            # Read before the write, in the transaction the write happens
            # in: afterwards there is nothing left to read the old set off,
            # and "what it used to be" is half of what makes this record
            # worth keeping.
            existing = uow.users.find_by_id(user_id)
            roles_before = (
                [role.name for role in existing.roles] if existing else []
            )

            updated_user = self.user_service.update_roles(uow, user_id, roles)
            uow.commit()

            log.info("User roles updated", target_user_id=user_id)
            audit.log_roles_changed(
                target_user_id=user_id,
                roles_before=roles_before,
                roles_after=[role.name for role in updated_user.roles],
            )
            return UserResponse.from_user(updated_user)
