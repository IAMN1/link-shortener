from dataclasses import dataclass

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.user import UserResponse
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.services.user_management_service import UserManagementService
from link_shortener.application.use_cases.admin.privilege_guard import (
    require_may_act_on_user,
)
from link_shortener.application.use_cases.base_use_case import BaseUseCase


@dataclass
class ActivateUserUseCase(BaseUseCase):
    """
    Reactivates a user account.

    Requires the ``admin:manage_users`` permission, and that the caller may
    reach this particular account -- see ``require_may_act_on``. The rule
    was written for the three acts that take authority away and this is the
    one that gives it back, which is the same reach seen from the other
    side: a caller holding ``admin:manage_users`` and nothing else could
    not suspend an ``auditor``, could not delete it and could not strip its
    roles, and could switch a suspended one back on -- so an account
    holding ``audit:view``, which no amount of ``admin:all`` confers,
    signed in again on the word of somebody who may not read a journal.

    Attributes:
        uow_factory: Callable factory for creating Unit of Work instances.
        user_service: Service that writes the new status.
        logger: Application logger.
        audit_logger: Audit logger, where the account is recorded.
    """

    uow_factory: UnitOfWorkFactory
    user_service: UserManagementService
    logger: Logger
    audit_logger: AuditLogger

    def execute(self, user_id: str, context: RequestContext) -> UserResponse:
        """
        Activate a user.

        Args:
            user_id: UUID of the user to activate.
            context: Request context with current admin info.

        Returns:
            UserResponse with updated status.

        Raises:
            DomainError: With code ``FORBIDDEN`` if the account holds a
                privileged permission the caller does not.
            UserNotFoundError: If no account carries that id.
        """
        log = self._get_logger(self.logger, context)
        audit = self._get_audit_logger(self.audit_logger, context)

        with self.uow_factory() as uow:
            # Before anything is written, and from the same transaction the
            # write runs in, as the three acts in the other direction ask
            # it. An id that names nobody passes here and is answered by
            # the service below.
            require_may_act_on_user(context, uow, user_id)

            updated_user = self.user_service.activate_user(uow, user_id)
            uow.commit()

        log.info("User activated", target_user_id=user_id)
        audit.log_user_activated(target_user_id=user_id)
        return UserResponse.from_user(updated_user)
