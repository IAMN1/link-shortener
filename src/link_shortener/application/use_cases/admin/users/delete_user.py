from dataclasses import dataclass

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.cache.link_cache import LinkCache
from link_shortener.application.ports.cache.link_service_stats_cache import (
    StatsCache,
)
from link_shortener.application.ports.cache.redirect_cache import RedirectCache
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.services.user_management_service import UserManagementService
from link_shortener.application.use_cases.admin.privilege_guard import (
    is_administrator,
    require_administrator_remains,
)
from link_shortener.application.use_cases.base_use_case import BaseUseCase


@dataclass
class DeleteUserUseCase(BaseUseCase):
    """
    Permanently removes a user, and every link they own, from the system.

    Requires ``admin:manage_users`` permission.

    The links go with the account, by decision of the owner of this
    project. Clearing ``urls.owner_id`` instead would leave them working,
    redirecting and belonging to nobody -- only a holder of
    ``link:delete_any`` could take them down, and nothing would say they
    exist. Deleting them is not reversible and is not meant to be.

    They are deleted here rather than left to the foreign key, because a row
    that disappears behind the application leaves its cache entries behind:
    every level would go on answering for a link that no longer exists, for
    the rest of its TTL, and nothing in the service could clear it. The
    foreign key is ``ON DELETE CASCADE`` all the same, as a backstop for a
    deletion done outside the application.

    Attributes:
        uow_factory: Callable factory for creating Unit of Work instances.
        user_service: Service that removes the account itself.
        cache: Link cache, cleared for every deleted link.
        redirect_cache: Redirect cache, cleared for every deleted link.
        stats_cache: Cache of service-wide totals, dropped once.
        logger: Application logger.
        audit_logger: Audit logger for significant events.
    """

    uow_factory: UnitOfWorkFactory
    user_service: UserManagementService
    cache: LinkCache
    redirect_cache: RedirectCache
    stats_cache: StatsCache
    logger: Logger
    audit_logger: AuditLogger

    def execute(self, user_id: str, context: RequestContext) -> bool:
        """
        Delete a user and everything they own.

        Args:
            user_id: UUID of the user to delete.
            context: Request context with admin info.

        Returns:
            ``True`` if the user was deleted, ``False`` if the user was not found.

        Raises:
            DomainError: If the caller is not authorized, or if this is the
                last administrator.
        """
        log = self._get_logger(self.logger, context)
        audit = self._get_audit_logger(self.audit_logger, context)

        with self.uow_factory() as uow:
            if is_administrator(uow, user_id):
                require_administrator_remains(uow, user_id)

            # The links first, in the transaction that removes the account:
            # either both go or neither does. Deleting the account first and
            # the links after would leave a window in which the links are
            # unowned and, if anything failed in between, permanently so.
            deleted_links = uow.links.delete_by_owner(user_id)

            deleted = self.user_service.delete_user(uow, user_id)
            if not deleted:
                return False

            uow.commit()

        # Only after the commit: an entry dropped for a deletion that then
        # rolls back is a cache miss, which costs a query, while an entry
        # left for a deletion that succeeded is a link that goes on
        # redirecting.
        self._drop_cached(deleted_links, log)

        for link in deleted_links:
            audit.log_url_deleted(
                short_code=link.short_code.value,
                original_url=link.original_url.value,
            )

        log.info(
            "User deleted",
            target_user_id=user_id,
            links_deleted=len(deleted_links),
        )
        # After the per-link records, and in addition to them. The links
        # are the trail of what was destroyed; this is the trail of the
        # account itself, and searching for one must not require reading
        # the other -- an account deleted while it owned nothing writes no
        # link records at all.
        audit.log_user_deleted(
            target_user_id=user_id, links_deleted=len(deleted_links)
        )
        return True

    def _drop_cached(self, links, log) -> None:
        """
        Take every deleted link out of every level that could answer for it.

        Args:
            links: The links just deleted.
            log: Bound logger.
        """
        if not links:
            return

        try:
            for link in links:
                self.cache.delete(link)
                self.redirect_cache.delete_redirect(link.short_code)
            # Fewer links than the totals say.
            self.stats_cache.delete_stats()
        except Exception as e:
            log.warning(
                "Cache invalidation failed after user deletion",
                error=str(e),
            )
