from dataclasses import dataclass, replace
import threading
import time


from link_shortener.application.context import RequestContext
from link_shortener.application.ports.cache.link_cache import LinkCache
from link_shortener.application.ports.cache.redirect_cache import RedirectCache
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import LinkNotFoundError, LinkRepository, ShortCode


@dataclass
class RedirectLinkUseCase(BaseUseCase):
    """
    Use case: Handle redirect by short code.

    Steps:
    1. Validate short code.
    2. Check L1 cache (redirect cache) for original URL.
    3. If not in L1, check L2 cache (full link cache).
    4. If not in L2, query repository.
    5. Increment click count (asynchronously).
    6. Cache URL in L1 and L2 for future requests.
    7. Return original URL.

    Click increment and audit are done asynchronously
    to not block the redirect response.
    """

    repository: LinkRepository
    link_cache: LinkCache
    redirect_cache: RedirectCache
    logger: Logger
    audit_logger: AuditLogger

    def execute(self, short_code_str: str, context: RequestContext) -> str:
        """
        Execute the redirect use case.

        Args:
            short_code_str: Short code as string.
            context: Request context with client metadata.

        Returns:
            Original URL to redirect to.

        Raises:
            LinkNotFoundError: If link not found.
            ValueError: If short code format is invalid.
            RuntimeError: If an unexpected error occurs.
        """

        log = self._get_logger(self.logger, context)
        start_time = time.perf_counter()
        log.debug("Redirect requested", code=short_code_str)

        try:
            # Step 1: Validate short code
            short_code = ShortCode(short_code_str)

            # Step 2: Check L1 cache (fastest)
            cached_url = self.redirect_cache.get_original_url(short_code)
            if cached_url:
                log.info("Redirect cache hit (L1)", code=short_code.value)
                
                # Asynchronously update click count and audit
                self._audit_and_update_async(short_code, context)
                
                return cached_url

            # Step 3: Check L2 cache (full link)
            cached_link = self.link_cache.get_by_code(short_code)
            if cached_link:
                log.info(
                    "Link cache hit for redirect (L2)", code=short_code.value
                )

                # Store in L1 cache for future fast redirects
                orig_url = cached_link.original_url.value
                self.redirect_cache.save_original_url(short_code, orig_url)

                self._audit_and_update_async(short_code, context)

                return orig_url

            # Step 4: Query repository
            link = self.repository.find_by_code(short_code)
            if not link:
                log.warning(
                    "Link not found for redirect:", code=short_code.value
                )
                raise LinkNotFoundError(short_code_str)

            orig_url = str(link.original_url.value)

            # Update the domain object (increment) for cache
            link.increment_clicks()
            self.repository.increment_clicks(short_code)

            # Step 6: Cache on all levels
            self.link_cache.save(link)

            log.info(
                "Redirect successful", code=short_code.value, url=orig_url[:50]
            )

            self.audit_logger.log_url_accessed(link, context)

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

    def _audit_and_update_async(
        self, short_code: ShortCode, context: RequestContext) -> None:
        """
        TODO: Replace with proper async task queue (Celery) later.

        Perform audit logging and click increment in a background thread.

        This is a temporary solution to avoid blocking the redirect response.
        In production, this should be replaced with a proper task queue (e.g., Celery).

        Args:
            short_code: Short code of the accessed link.
            context: Request context (copied to the background thread).
        """

        context_copy = replace(context) # bcs of frozen=True

        def task():

            thread_log = self._get_logger(self.logger, context_copy)

            try:
                # Try to get link from cache first (fast)
                link = self.link_cache.get_by_code(short_code)
                if not link:
                    link = self.repository.find_by_code(short_code)
                
                if link:
                    # Audit
                    self.audit_logger.log_url_accessed(link, context_copy)
                    
                    # Increment in repository
                    self.repository.increment_clicks(short_code)

                    # Update local link object for cache
                    link.increment_clicks()
                    # Refresh cache with updated link
                    self.link_cache.save(link)

                    thread_log.debug(
                        "Background click increment and audit completed",
                        short_code=short_code.value,
                        new_clicks=link.clicks,
                    )

                else:
                    thread_log.error(
                        "Background task failed: link not found", 
                        code=short_code.value
                    )

            except Exception as e:
                thread_log.error(
                    "Background task failed",
                    short_code=short_code.value,
                    error=str(e),
                )
        thread = threading.Thread(target=task)
        thread.daemon = True
        thread.start()
