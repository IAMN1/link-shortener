from dataclasses import dataclass

from link_shortener.domain import (
    LinkNotFoundError, LinkVisit, ShortCode, ValidationError,
)
from link_shortener.application.ports.cache.link_cache import LinkCache
from link_shortener.application.ports.cache.redirect_cache import (
    RedirectCache,
)
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.context import RequestContext
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.use_cases.base_use_case import BaseUseCase


@dataclass
class UpdateLinkStatsUseCase(BaseUseCase):
    """
    Records one opening of a link: the counter, and the event behind it.

    Designed to be called from a Celery worker. It uses its own UoW
    to ensure a fresh transaction.

    The counter and the visit row are written in the same transaction, so
    the two cannot disagree about how many times a link was opened -- a
    chart that adds up to a different number than the figure beside it is
    worse than no chart.

    What the visit remembers about the caller is reduced before it is
    stored: a network instead of an address, a device class and a browser
    family instead of the header that named them. See
    ``domain.value_objects.visitor``.

    It writes to no cache, and the comment at the end of ``execute`` says
    at length why. It does **drop** one entry, in one branch: when the row
    is not there to increment. Those are opposite acts and the difference
    is the whole of it -- a write puts back what a delete removed, while a
    drop can only agree with a database that has already spoken.

    That branch is how a link deleted in another process stops
    redirecting. With ``REDIS_ENABLED=false`` each process holds its own
    cache, so a ``flask link delete`` at a shell empties the shell's copy
    and leaves the server's untouched: measured on the arrangement the
    local profile ships, the command reported the link deleted, the API
    answered ``404``, and the redirect went on answering ``302`` for six
    minutes across two ``cache clear`` runs. This runs on every redirect
    and is the one thing that always asks the database, so it is where the
    server finds out.

    Both levels are dropped, not one. Dropping L1 alone was written first
    and measured wrong: the next request missed L1, found the entity still
    in L2, answered from it and warmed L1 back up, so the redirect went on
    working with the warning printed on every one of them. The entity
    cache is what makes L1 come back, so it has to go with it.

    Attributes:
        uow_factory: Opens the transaction this runs in.
        cache: The L2 entity, dropped when the row is gone. Never written
            here.
        redirect_cache: The L1 entry, dropped with it. Never written here.
        logger: Where the outcome is recorded.
        record_visits: Whether to store the event as well as the counter.
            Off, the service keeps counting and every chart with time on
            an axis stays empty -- which is the state the service was in
            before the table existed.
    """
    uow_factory: UnitOfWorkFactory
    cache: LinkCache
    redirect_cache: RedirectCache
    logger: Logger
    record_visits: bool = True

    def execute(self, short_code_str: str, context: RequestContext) -> None:
        """
        Increment the counter and record the visit behind it.

        Args:
            short_code_str: Short code as string (from Celery task).
            context: Request context. Carries the address and User-Agent
                the visit is reduced from, as well as the logging fields.
        """
        log = self._get_logger(self.logger, context)
        log.debug("Background task: updating link stats", short_code=short_code_str)

        try:
            short_code = ShortCode(short_code_str)
        except ValidationError as e:
            # `ValidationError`, not `ValueError`: it descends from
            # `DomainError`, so the `ValueError` this used to name never
            # matched and the error left the use case instead. The task
            # calling it retries on any exception, which turned a code no
            # link can carry -- a truncated path, a scanner walking the
            # space -- into three attempts a minute apart, none of which
            # could have succeeded.
            log.error("Invalid short code format", short_code=short_code_str, error=str(e))
            return

        with self.uow_factory() as uow:
            try:
                uow.links.increment_clicks(short_code)
            except LinkNotFoundError:
                # The database has said the row is gone, and this process
                # may still be handing out its redirect. Dropping the entry
                # cannot resurrect anything -- there is nothing to
                # resurrect -- and it is the only moment a process that did
                # not perform the deletion learns of it.
                self.redirect_cache.delete_redirect(short_code)
                self.cache.delete_by_code(short_code)
                log.warning(
                    "Link not found during stats update; both cache levels "
                    "for it were dropped in this process"
                )
                return

            if self.record_visits:
                # Read after the update rather than before it: the update
                # is what establishes the link exists, and a link deleted
                # between the two would otherwise get a visit row pointing
                # at nothing. Costs one indexed lookup, on a path that is
                # already off the request -- except where Celery is off,
                # and there the redirect has just done the same lookup.
                link = uow.links.find_by_code(short_code)
                if link is not None:
                    uow.link_visits.record(
                        LinkVisit.record(
                            link_id=link.id,
                            remote_addr=context.remote_addr,
                            user_agent=context.user_agent,
                        )
                    )

            uow.commit()

        # The cache is deliberately not refreshed here.
        #
        # This write is the one that resurrected deleted links. It lands
        # after its own transaction closes, so a DELETE that committed and
        # invalidated in between finds nothing left to invalidate -- and the
        # entry reappears behind the deletion, redirecting for the rest of
        # CACHE_LINK_TTL while the API answers 404 for the same code.
        # Reproduced over plain HTTP with no privileges at all: 24 concurrent
        # readers against one delete, roughly one resurrection in ten. With
        # the click task prevented from running, none.
        #
        # Nothing was buying anything with it. The redirect reads only the
        # URL and the expiry, the info endpoints do not read the cache, and
        # the deduplication paths confirm what they find against the
        # database -- so the click count in a cached entity is read by
        # nobody. Warming stays where it belongs: on the redirect's own
        # repository hit.
