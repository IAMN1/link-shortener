from dataclasses import dataclass
from typing import Callable

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.auth.authorization_service import AuthorizationService
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.services.role_management_service import RoleManagementService
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import DomainError, SystemPermissions


@dataclass
class DeleteRoleUseCase(BaseUseCase):
    """
    Deletes a role that is not marked as a system role.

    Requires the caller to have the ``admin:manage_roles`` permission.
    """
    uow_factory: Callable[[], UnitOfWork]
    role_service: RoleManagementService
    authorization_service: AuthorizationService
    logger: Logger

    def execute(
            self,
            role_name: str,
            context: RequestContext
    ) -> bool:
        """
        Delete a role by name.

        Args:
            role_name: Unique name of the role to delete.
            context: Request context containing current user info.

        Returns:
            ``True`` if the role was successfully deleted.

        Raises:
            DomainError: If the user is not authorized, the role is a system role,
                or the role does not exist.
        """

        log = self._get_logger(self.logger, context)

        with self.uow_factory() as uow:
            # Resolve current user from context
            user = None
            if context and context.current_user:
                user = uow.users.find_by_id(context.current_user.id)

            # Authorize: only users with admin:manage_roles can delete roles
            if not self.authorization_service.is_allowed(user, SystemPermissions.ADMIN_MANAGE_ROLES.value):
                log.warning(
                    "Unauthorized attempt to delete role",
                    user_id=user.id if user else None
                )
                raise DomainError("Not authorized to manage roles", code="FORBIDDEN")

            try:
                self.role_service.delete_role(uow, role_name)
                uow.commit()

                log.info(
                    "Role deleted",
                    role_name=role_name,
                    deleted_by=user.id if user else "system"
                )
                return True
            except ValueError as e:
                log.error("Role deletion failed", error=str(e))
                raise DomainError(str(e), code="ROLE_DELETION_FAILED")
