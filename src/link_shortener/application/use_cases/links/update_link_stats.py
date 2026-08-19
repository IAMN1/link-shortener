from dataclasses import dataclass

from link_shortener.domain import (
    LinkNotFoundError, LinkVisit, ShortCode, ValidationError,
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

    It touches no cache: a write refreshing the cached entity would land
    after its own transaction closed, which is how a deleted link comes
    back to life on the redirect path.

    Attributes:
        uow_factory: Opens the transaction this runs in.
        logger: Where the outcome is recorded.
        record_visits: Whether to store the event as well as the counter.
            Off, the service keeps counting and every chart with time on
            an axis stays empty -- which is the state the service was in
            before the table existed.
    """
    uow_factory: UnitOfWorkFactory
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
                log.warning("Link not found during stats update")
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
