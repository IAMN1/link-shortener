from dataclasses import dataclass
from typing import Callable

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.user import UserResponse
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.services.user_management_service import UserManagementService
from link_shortener.application.use_cases.admin.privilege_guard import (
    is_administrator,
    require_administrator_remains,
)
from link_shortener.application.use_cases.base_use_case import BaseUseCase


@dataclass
class DeactivateUserUseCase(BaseUseCase):
    """
    Deactivates a user account (they cannot log in).

    Requires ``admin:manage_users`` permission.
    """

    uow_factory: Callable[[], UnitOfWork]
    user_service: UserManagementService
    logger: Logger

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

        with self.uow_factory() as uow:
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

            return UserResponse.from_user(updated_user)
