from dataclasses import dataclass

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.user import UserResponse
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.services.user_management_service import UserManagementService
from link_shortener.application.use_cases.base_use_case import BaseUseCase


@dataclass
class ActivateUserUseCase(BaseUseCase):
    """
    Reactivates a user account.

    Requires the ``admin:manage_users`` permission.

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
            DomainError: If the caller is not authorized or the user does not exist.
        """
        log = self._get_logger(self.logger, context)
        audit = self._get_audit_logger(self.audit_logger, context)

        with self.uow_factory() as uow:
            updated_user = self.user_service.activate_user(uow, user_id)
            uow.commit()

            log.info("User activated", target_user_id=user_id)
            audit.log_user_activated(target_user_id=user_id)
            return UserResponse.from_user(updated_user)
