from dataclasses import dataclass
from typing import Callable

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.cache.link_cache import LinkCache
from link_shortener.application.ports.cache.redirect_cache import RedirectCache
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import ShortCode
from link_shortener.domain.exceptions import ValidationError


@dataclass
class DeleteLinkUseCase(BaseUseCase):
    """
    Deletes a short link.

    Requires the caller to have the ``link:delete`` permission.
    """

    uow_factory: Callable[[], UnitOfWork]
    cache: LinkCache
    redirect_cache: RedirectCache
    logger: Logger
    audit_logger: AuditLogger

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
                link = uow.links.find_by_code(short_code)
                if not link:
                    log.warning("Link not found for deletion", code=short_code_str)
                    return False

                deleted = uow.links.delete(short_code)
                if not deleted:
                    return False

                uow.commit()

                # Invalidate caches so deleted link is not served stale
                try:
                    self.cache.delete(short_code)
                    self.redirect_cache.delete(short_code)
                except Exception as e:
                    log.warning(
                        "Cache invalidation failed after link deletion",
                        code=short_code_str,
                        error=str(e),
                    )

                audit.log_url_deleted(
                    short_code=link.short_code.value,
                    original_url=link.original_url.value
                )

                log.info("Link deleted successfully", code=link.short_code.value)
                return deleted
        except (ValueError, ValidationError) as e:
            log.error("Invalid short code format", error=str(e))
            return False
