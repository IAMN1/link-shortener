from dataclasses import dataclass

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.user import UserResponse
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.services.user_management_service import UserManagementService
from link_shortener.application.use_cases.admin.privilege_guard import (
    is_administrator,
    require_administrator_remains,
    require_may_act_on_user,
)
from link_shortener.application.use_cases.base_use_case import BaseUseCase


@dataclass
class DeactivateUserUseCase(BaseUseCase):
    """
    Deactivates a user account (they cannot log in).

    Requires ``admin:manage_users`` permission.

    Attributes:
        uow_factory: Callable factory for creating Unit of Work instances.
        user_service: Service that writes the new status.
        logger: Application logger.
        audit_logger: Audit logger, where the account and the sessions it
            lost are recorded.
    """

    uow_factory: UnitOfWorkFactory
    user_service: UserManagementService
    logger: Logger
    audit_logger: AuditLogger

    def execute(self, user_id: str, context: RequestContext) -> UserResponse:
        """
        Deactivate a user.

        Args:
            user_id: UUID of the user.
            context: Request context with admin info.

        Returns:
            UserResponse with updated status.

        Raises:
            DomainError: If not authorized, or if this is the last
                administrator.
        """
        log = self._get_logger(self.logger, context)
        audit = self._get_audit_logger(self.audit_logger, context)

        with self.uow_factory() as uow:
            # Before the count, for the reason ``DeleteUserUseCase`` gives:
            # the refusal a caller is entitled to is the one about their own
            # authority, not the one about the system's last administrator.
            require_may_act_on_user(context, uow, user_id)

            # Blocking the last administrator locks the admin surface for
            # everyone; recovery would need a shell.
            if is_administrator(uow, user_id):
                require_administrator_remains(uow, user_id)

            updated_user = self.user_service.deactivate_user(uow, user_id)

            # Retire the refresh tokens in the same transaction. Blocking the
            # account already stops every request, but leaving the sessions
            # alive would hand access straight back if the account is later
            # reactivated.
            revoked = uow.refresh_sessions.revoke_all_for_user(user_id)
            uow.commit()

        log.info(
            "User deactivated", target_user_id=user_id, sessions_revoked=revoked
        )
        audit.log_user_deactivated(
            target_user_id=user_id, sessions_revoked=revoked
        )

        return UserResponse.from_user(updated_user)
