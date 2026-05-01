from dataclasses import dataclass
import time
from typing import Callable


from link_shortener.application.context import RequestContext
from link_shortener.application.ports.cache.link_cache import LinkCache
from link_shortener.application.ports.cache.redirect_cache import RedirectCache
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.task_queue import TaskQueue
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import LinkNotFoundError, ShortCode


@dataclass
class RedirectLinkUseCase(BaseUseCase):
    """
    Resolve a short code to the original URL for HTTP redirect.

    Caching strategy:
    - L1 (RedirectCache): maps short_code - original_url for fastest lookup.
    - L2 (LinkCache): full Link object for secondary access.

    After returning the URL, a background task is enqueued to increment
    click counts and update audit logs asynchronously.
    """

    uow_factory: Callable[[], UnitOfWork]
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
            LinkNotFoundError: If the short code does not exist.
            ValueError: If the short code format is invalid.
            RuntimeError: On unexpected failures.
        """

        log = self._get_logger(self.logger, context)
        audit = self._get_audit_logger(self.audit_logger, context)

        start_time = time.perf_counter()
        log.debug("Redirect requested", code=short_code_str)

        try:
            # Step 1: Validate short code
            short_code = ShortCode(short_code_str)

            # Step 2: Check L1 cache (fastest)
            cached_url = self.redirect_cache.get_original_url(short_code)
            if cached_url:
                # Asynchronously update click count and audit
                self.task_queue.enqueue_link_accessed(short_code.value, context)

                log.info("Redirect cache hit (L1)", code=short_code.value)
                audit.log_url_accessed(short_code=short_code.value, original_url=cached_url)

                return cached_url

            # Step 3: Check L2 cache (full link)
            cached_link = self.link_cache.get_by_code(short_code)
            if cached_link:

                # Store in L1 cache for future fast redirects
                orig_url = cached_link.original_url.value
                self.redirect_cache.save_original_url(short_code, orig_url)

                self.task_queue.enqueue_link_accessed(short_code.value, context)

                log.info("Link cache hit (L2)", code=short_code.value)
                audit.log_url_accessed(short_code=short_code.value, original_url=orig_url)

                return orig_url

            # Step 4: Query repository
            with self.uow_factory(read_only=True) as uow:
                link = uow.links.find_by_code(short_code)
                if not link:
                    log.warning("Link not found:", code=short_code.value)
                    raise LinkNotFoundError(short_code_str)

                orig_url = str(link.original_url.value)
                # Step 6: Cache on all levels
                self.link_cache.save(link)

            # Enqueue background stat update
            self.task_queue.enqueue_link_accessed(short_code.value, context)

            log.info(
                "Redirect successful", code=short_code.value, url=orig_url[:50]
            )
            audit.log_url_accessed(short_code=short_code.value, original_url=orig_url)

            return orig_url

        except ValueError as e:
            log.error(
                "Invalid short code format", code=short_code_str, error=str(e)
            )
            raise ValueError(f"Invalid short code: {str(e)}")

        except LinkNotFoundError:
            raise

        except Exception as e:
            log.exception(
                "Error during redirect",
                exc_info=str(e),
                short_code=short_code_str,
            )
            raise RuntimeError(f"Failed to redirect: {str(e)}")
        finally:
            duration = time.perf_counter() - start_time
            log.debug("Execution time", duration_ms=round(duration * 1000, 2))
