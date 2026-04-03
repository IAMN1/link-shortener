from dataclasses import dataclass

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain.repositories.link_repository import LinkRepository
from link_shortener.domain.value_objects.short_code import ShortCode


@dataclass
class DeleteLinkUseCase(BaseUseCase):
    """
    Use case: delete a short link by its code.
    """

    repository: LinkRepository
    logger: Logger
    audit_logger: AuditLogger

    def execute(self, short_code_str: str, context: RequestContext) -> bool:
        """
        Execute deletion.

        Returns:
            True if link was deleted, False if not found.
        """
        log = self._get_logger(self.logger, context)
        audit = self._get_audit_logger(self.audit_logger, context)

        try:
            short_code = ShortCode(short_code_str)
            link = self.repository.find_by_code(short_code_str)
            if not link:
                log.warning("Link not found for deletion", code=short_code_str)
                return False
            
            deleted = self.repository.delete(short_code)
            if deleted:
                audit.log_url_deleted(
                    short_code=link.short_code.value,
                    original_url=link.original_url.value
                )
                log.info("Link deleted successfully", code=link.short_code.value)
            return deleted
        except ValueError as e:
            log.error("Invalid short code format", error=str(e))
            return False