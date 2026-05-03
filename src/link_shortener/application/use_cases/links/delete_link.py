from dataclasses import dataclass
from typing import Callable

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.auth.authorization_service import AuthorizationService
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import ( DomainError, ShortCode)
from link_shortener.domain.system_permissions import SystemPermissions


@dataclass
class DeleteLinkUseCase(BaseUseCase):
    """
    Deletes a short link.

    Requires the caller to have the ``link:delete`` permission.
    """

    uow_factory: Callable[[], UnitOfWork]
    logger: Logger
    audit_logger: AuditLogger
    authz: AuthorizationService

    def execute(self, short_code_str: str, context: RequestContext) -> bool:
        """
        Delete a link.

        Args:
            short_code_str: Short code to delete.
            context: Request context containing current user info.

        Returns:
            True if the link was deleted, False if it did not exist.

        Raises:
            DomainError: If the user is not authorized.
            ValueError: If the short code format is invalid.
        """
        log = self._get_logger(self.logger, context)
        audit = self._get_audit_logger(self.audit_logger, context)

        try:
            short_code = ShortCode(short_code_str)

            with self.uow_factory() as uow:
                # Load user if authenticated
                user = None
                if context.current_user:
                    user = uow.users.find_by_id(context.current_user.id)

                # Fetch link
                link = uow.links.find_by_code(short_code)
                if not link:
                    log.warning("Link not found for deletion", code=short_code_str)
                    return False

                # Authorization: allow deletion by owner or by admin
                can_delete_any = self.authz.is_allowed(user, SystemPermissions.LINK_DELETE_ANY.value)
                can_delete_own = self.authz.is_allowed(user, SystemPermissions.LINK_DELETE_OWN.value)
                if not can_delete_any and not (
                    can_delete_own
                    and link.owner
                    and user
                    and link.owner.value == user.id
                ):
                    log.warning("Unauthorized delete attempt", user_id=user.id if user else None)
                    raise DomainError("Not authorized to delete this link", code="FORBIDDEN")
                
                deleted = uow.links.delete(short_code)
                if not deleted:
                    return False

                uow.commit()

                audit.log_url_deleted(
                    short_code=link.short_code.value,
                    original_url=link.original_url.value
                )

                log.info("Link deleted successfully", code=link.short_code.value)

                return deleted

        except ValueError as e:
            log.error("Invalid short code format", error=str(e))
            return False
