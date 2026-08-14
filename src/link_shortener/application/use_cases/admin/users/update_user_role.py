from dataclasses import dataclass
from typing import List

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.user import UserResponse
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.services.user_management_service import UserManagementService
from link_shortener.application.use_cases.admin.privilege_guard import (
    is_administrator,
    require_administrator_remains,
    require_may_grant_roles,
    would_keep_admin,
)
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import DomainError


@dataclass
class UpdateUserRolesUseCase(BaseUseCase):
    """
    Replaces all roles assigned to a user.

    Requires ``admin:manage_users`` permission.
    """

    uow_factory: UnitOfWorkFactory
    user_service: UserManagementService
    logger: Logger

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
            DomainError: If the caller is not authorized, if a role carries
                a permission the caller does not hold, or if the change
                would leave the system without an administrator.
        """
        log = self._get_logger(self.logger, context)

        with self.uow_factory() as uow:
            roles = []
            for name in role_names:
                role = uow.roles.get_by_name(name)
                if not role:
                    raise DomainError(f"Role '{name}' not found", code="VALIDATION_ERROR")
                roles.append(role)

            # ``admin:manage_users`` is not a shorter spelling of
            # ``admin:all``: assign yourself the admin role, read the
            # permissions back. Nothing asked whether the caller was
            # entitled to what they were handing out.
            require_may_grant_roles(context, uow, roles)

            # Asked in the same transaction that will write the change, and
            # only when it actually takes the permission away.
            if is_administrator(uow, user_id) and not would_keep_admin(roles):
                require_administrator_remains(uow, user_id)

            updated_user = self.user_service.update_roles(uow, user_id, roles)
            uow.commit()

            log.info("User roles updated", target_user_id=user_id)
            return UserResponse.from_user(updated_user)
