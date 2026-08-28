from dataclasses import dataclass
import time


from link_shortener.application.context import RequestContext
from link_shortener.application.ports.cache.link_cache import LinkCache
from link_shortener.application.ports.cache.redirect_cache import RedirectCache
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.task_queue import TaskQueue
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import (
    LinkExpiredError, LinkNotFoundError, ShortCode
)


@dataclass
class RedirectLinkUseCase(BaseUseCase):
    """
    Resolve a short code to the original URL for HTTP redirect.

    Caching strategy:
    - L1 (RedirectCache): destination plus expiry, enough to answer a
      redirect on its own. A hit ends the request.
    - L2 (LinkCache): full Link entity, consulted only when L1 cannot
      answer.

    After returning the URL, a background task is enqueued to increment
    click counts and update audit logs asynchronously.
    """

    uow_factory: UnitOfWorkFactory
    link_cache: LinkCache
    redirect_cache: RedirectCache
    logger: Logger
    audit_logger: AuditLogger
    task_queue: TaskQueue

    def execute(self, short_code_str: str, context: RequestContext) -> str:
        """
        Execute the redirect.

        Args:
            short_code_str: Short code from the URL path.
            context: Request context (contains IP, User-Agent, etc.).

        Returns:
            The original URL to redirect to.

        Raises:
            LinkNotFoundError: If no link carries this code, a string the
                format rules refuse included -- on this route above all,
                which is where a single unmatched segment lands, a
                malformed code is a page that is not there rather than a
                bad request.
            LinkExpiredError: If a link carries the code but its lifetime
                is over, which the status table answers 410.

        Anything else raised below is logged and re-raised as it came:
        nothing here translates a failure into an exception of its own.
        """

        log = self._get_logger(self.logger, context)
        audit = self._get_audit_logger(self.audit_logger, context)

        start_time = time.perf_counter()
        log.debug("Redirect requested", code=short_code_str)

        try:
            # Step 1: Read the code, or answer that no link carries it
            short_code = self._code_to_look_up(short_code_str)

            # Step 2: Ask L1. A hit is a complete answer and ends the
            # request here -- that is the whole point of the level.
            #
            # It can only end the request because the entry carries its own
            # expiry: while L1 held a bare URL string it could not say
            # whether the link was still alive, so every hit had to consult
            # L2 for the answer and the level saved nothing at all. An entry
            # the cache cannot vouch for -- unreadable, written in the old
            # format, or belonging to another code -- is reported as a miss,
            # so it falls through to the levels that can answer.
            cached_redirect = self.redirect_cache.get_redirect(short_code)

            if cached_redirect:
                if cached_redirect.is_expired():
                    # Belt and braces: the entry's own lifetime is already
                    # capped at the link's, so this should have vanished by
                    # itself. The two clocks are not the same one.
                    log.info("Link expired (L1)", short_code=short_code.value)
                    raise LinkExpiredError(short_code.value)

                log.info(
                    "Redirect cache hit", code=short_code.value, cache_level="L1"
                )
                return self._answer(
                    short_code, cached_redirect.original_url, context, audit
                )

            # Step 3: L1 could not answer. Try the full entity.
            cached_link = self.link_cache.get_by_code(short_code)

            if cached_link:
                if cached_link.is_expired():
                    log.info("Link expired (cache)", short_code=short_code.value)
                    raise LinkExpiredError(short_code.value)

                orig_url = cached_link.original_url.value
                # Warm L1 from the entity, so the next request for this code
                # is answered by one lookup instead of two.
                self.redirect_cache.save_redirect(
                    short_code, orig_url, cached_link.expires_at
                )

                log.info(
                    "Redirect cache hit", code=short_code.value, cache_level="L2"
                )
                return self._answer(short_code, orig_url, context, audit)

            # Step 4: Query repository
            with self.uow_factory(read_only=True) as uow:
                link = uow.links.find_by_code(short_code)
                if not link:
                    log.warning("Link not found:", code=short_code.value)
                    raise LinkNotFoundError(short_code_str)

                if link.is_expired():
                    log.info("Link expired", short_code=short_code.value)
                    raise LinkExpiredError(short_code.value)

                orig_url = str(link.original_url.value)
                # Cache on all levels. save() writes the L1 redirect key too,
                # so a stale L1 entry left over from an evicted L2 is
                # overwritten here rather than outliving it.
                self.link_cache.save(link)

            # The destination is not written here. It comes from storage
            # through ``from_storage``, which skips ``_validate_no
            # _credentials`` on purpose -- rows admitted under older rules
            # have to stay readable -- so a legacy row carries its
            # password straight into application.log, on every cache-miss
            # redirect. The audit line below records the same URL through
            # ``mask_url``; the short code identifies the link here.
            log.info("Redirect successful", code=short_code.value)
            return self._answer(short_code, orig_url, context, audit)

        except (ValueError, LinkNotFoundError, LinkExpiredError):
            raise

        except Exception as e:
            log.exception(
                "Error during redirect",
                exc_info=str(e),
                short_code=short_code_str,
            )
            raise
        finally:
            duration = time.perf_counter() - start_time
            log.debug("Execution time", duration_ms=round(duration * 1000, 2))

    def _answer(
        self,
        short_code: ShortCode,
        original_url: str,
        context: RequestContext,
        audit: AuditLogger,
    ) -> str:
        """
        Hand back a destination, having recorded that it was handed back.

        Three branches answer a redirect -- the L1 entry, the cached entity
        and the repository read -- and each has to count the visit and write
        the audit line. Written out three times, the two calls are two
        chances to add a branch that answers without counting: the visit
        would be missing from ``link_visits`` and the redirect from
        ``audit.log``, on whichever share of traffic that branch happens to
        serve, with everything else about the response identical. The same
        shape has already cost this project once -- ``CountingAuditLogger``
        exists because a counter beside each ``audit.log_*`` call was a
        counter the fifteenth event forgot.

        The log line stays with the branch: it names which level answered,
        which is the one thing the three do not share.

        Args:
            short_code: The code that was asked for.
            original_url: Where it leads.
            context: Request context, carried into the background task.
            audit: Audit logger, already bound to the request.

        Returns:
            The destination, for the controller to redirect to.
        """
        self.task_queue.enqueue_link_accessed(short_code.value, context)
        audit.log_url_accessed(
            short_code=short_code.value, original_url=original_url
        )
        return original_url
