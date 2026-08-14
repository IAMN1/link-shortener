from dataclasses import dataclass
from typing import Callable, Optional

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.auth.authorization_service import (
    AuthorizationService,
)
from link_shortener.application.ports.cache.link_cache import LinkCache
from link_shortener.application.ports.cache.link_service_stats_cache import (
    StatsCache,
)
from link_shortener.application.ports.cache.redirect_cache import RedirectCache
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import (
    DomainError, Link, LinkNotFoundError, SystemPermissions
)


@dataclass
class DeleteLinkUseCase(BaseUseCase):
    """
    Deletes a short link.

    Ownership is decided here, from the row this use case loads inside its
    own transaction, rather than from a value the caller supplies: read any
    other way, the answer is only as trustworthy as that read.

    Attributes:
        uow_factory: Callable that returns a new Unit of Work instance.
        cache: Implementation of the link cache (L2).
        redirect_cache: Implementation of the redirect cache (L1).
        stats_cache: Cache of service-wide totals, dropped alongside the link.
        logger: Application logger.
        audit_logger: Audit logger.
        authorization_service: Service that answers permission questions.
    """

    uow_factory: Callable[[], UnitOfWork]
    cache: LinkCache
    redirect_cache: RedirectCache
    stats_cache: StatsCache
    logger: Logger
    audit_logger: AuditLogger
    authorization_service: AuthorizationService

    def execute(
        self,
        short_code_str: str,
        context: RequestContext,
        *,
        enforce_ownership: bool,
        authorized_link_id: Optional[str] = None,
    ) -> bool:
        """
        Delete a link.

        Args:
            short_code_str: Short code to delete.
            context: Request context containing current user info.
            enforce_ownership: Whether the requester must own the link or
                hold ``link:delete_any``. Keyword-only and without a
                default on purpose: a caller that forgets it gets a
                ``TypeError``, not a silent bypass.
            authorized_link_id: The link a verified deletion token was
                issued for. A guest link has no owner, so ownership can
                never match for it; the token is the only thing that can
                speak for its creator.

        Returns:
            True if the link was deleted, False if it did not exist.

        Raises:
            DomainError: If the requester may not delete this link.
        """
        log = self._get_logger(self.logger, context)
        audit = self._get_audit_logger(self.audit_logger, context)

        try:
            short_code = self._code_to_look_up(short_code_str)

            with self.uow_factory() as uow:
                link = uow.links.find_by_code(short_code)
                if not link:
                    log.warning("Link not found for deletion", code=short_code_str)
                    # The row is gone and the answer is still 404, but the
                    # cache is dropped anyway. A cache entry surviving a row
                    # is exactly the state a second DELETE is issued to
                    # clear, and returning early left the operator with a
                    # redirect that works for a link every API surface
                    # calls deleted, and no command able to touch it.
                    self._drop_cached(short_code, None, log)
                    return False

                # Asked before anything is written, and answered from the
                # row just read. An expired link is still deletable: expiry
                # decides what may be served, not who owns what.
                if enforce_ownership and link.id != authorized_link_id:
                    self._require_may_delete(link, context, uow, log)

                # The row that was judged, named by its identity. Asking for
                # "the row under this code" a second time can answer with a
                # different one: a code freed by a concurrent delete is
                # available to the next link, and codes are derived from the
                # URL, so which link takes it is not unguessable.
                deleted = uow.links.delete(link.id)
                if not deleted:
                    return False

                uow.commit()

                self._drop_cached(short_code, link, log)

                audit.log_url_deleted(
                    short_code=link.short_code.value,
                    original_url=link.original_url.value
                )

                log.info("Link deleted successfully", code=link.short_code.value)
                return deleted
        except LinkNotFoundError:
            # A code that cannot exist and a code nobody has taken are the
            # same answer to the caller. LinkNotFoundError specifically: a
            # wider except would report any failure in the block above as
            # "no such link".
            log.warning("Not a usable short code", code=short_code_str)
            return False

    def _drop_cached(self, short_code, link, log) -> None:
        """
        Take the link out of every level that could still answer for it.

        The entity is passed where there is one, not just the code: the
        deduplication entry is keyed by hash and scope, and dropping only
        what a code can name leaves it behind to answer for a link that no
        longer exists. When the row is already gone there is no entity, and
        the two code-keyed levels are dropped on their own -- which is the
        only way an entry that outlived its row can be cleared through the
        product at all.

        Args:
            short_code: The code being deleted.
            link: The entity just deleted, or ``None`` if the row was gone.
            log: Bound logger.
        """
        try:
            if link is not None:
                self.cache.delete(link)
            else:
                self.cache.delete_by_code(short_code)
            self.redirect_cache.delete_redirect(short_code)
            # One fewer link than the totals say.
            self.stats_cache.delete_stats()
        except Exception as e:
            log.warning(
                "Cache invalidation failed after link deletion",
                code=short_code.value,
                error=str(e),
            )

    def _require_may_delete(
        self,
        link: Link,
        context: RequestContext,
        uow: UnitOfWork,
        log: Logger,
    ) -> None:
        """
        Check that the requester may delete this particular link.

        The user is re-read inside the active transaction rather than taken
        from the request context: the context carries role names only, and
        permissions are what the decision needs.

        Args:
            link: The link about to be deleted.
            context: Request context containing current user info.
            uow: Active Unit of Work.
            log: Bound logger.

        Raises:
            DomainError: If the requester may not delete this link
                (code=``FORBIDDEN``).
        """
        requester = self._load_requester(context, uow)
        if requester is None:
            raise DomainError("Authentication required", code="UNAUTHENTICATED")

        owner_id = link.owner.value if link.owner else None
        owns_it = owner_id is not None and owner_id == requester.id

        required = (
            SystemPermissions.LINK_DELETE_OWN.value
            if owns_it
            else SystemPermissions.LINK_DELETE_ANY.value
        )

        if not self.authorization_service.is_allowed(requester, required):
            log.warning(
                "Link deletion refused",
                code=link.short_code.value,
                required_permission=required,
            )
            raise DomainError(
                "You are not allowed to delete this link", code="FORBIDDEN"
            )

    @staticmethod
    def _load_requester(context: RequestContext, uow: UnitOfWork):
        """
        Load the domain user the request is acting as, if any.

        Args:
            context: Request context containing current user info.
            uow: Active Unit of Work.

        Returns:
            The ``User`` entity, or ``None`` for an anonymous request.
        """
        if context.current_user is None:
            return None
        return uow.users.find_by_id(context.current_user.id)
