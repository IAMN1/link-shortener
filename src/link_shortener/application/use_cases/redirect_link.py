from dataclasses import dataclass
import threading
from typing import Optional


from link_shortener.application.ports.cache.link_cache import LinkCache
from link_shortener.application.ports.cache.redirect_cache import RedirectCache
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.domain import LinkNotFoundError, LinkRepository, ShortCode


@dataclass
class RedirectLinkUseCase:
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

    def execute(self, short_code_str: str, user_ip: Optional[str] = None, user_agent: Optional[str] = None) -> str:
        """
        Execute the redirect use case.

        Args:
            short_code_str (str): Short code as string.
            user_ip (Optional[str], optional): Client IP (for audit). 
                Defaults to None.
            user_agent (Optional[str], optional): Client User-Agent (for audit). 
                Defaults to None.

        Raises:
            LinkNotFoundError: If link not found.
            ValueError: If short code format is invalid.
            RuntimeError: _description_

        Returns:
            str: Original URL to redirect to.
        """
        try:
            # Step 1: Validate short code
            short_code = ShortCode(short_code_str)

            self.logger.debug("Redirect requested for", code=short_code.value)

            # Step 2: Check L1 cache (fastest)
            cached_url = self.redirect_cache.get_original_url(short_code)
            if cached_url:
                self.logger.info("Redirect cache hit (L1)", code=short_code.value)
                
                # Asynchronously update click count and audit
                self._audit_and_update_async(short_code, user_ip, user_agent)
                
                return cached_url

            # Step 3: Check L2 cache (full link)
            cached_link = self.link_cache.get_by_code(short_code)
            if cached_link:
                self.logger.info(
                    "Link cache hit for redirect (L2)", code=short_code.value
                )

                # Store in L1 cache for future fast redirects
                orig_url = cached_link.original_url.value
                self.redirect_cache.save_original_url(short_code, orig_url)

                self._audit_and_update_async(short_code, user_ip, user_agent)

                return orig_url

            # Step 4: Query repository
            link = self.repository.find_by_code(short_code)
            if not link:
                self.logger.warning(
                    "Link not found for redirect:", code=short_code.value
                )
                raise LinkNotFoundError(short_code_str)

            orig_url = str(link.original_url.value)

            # Update the domain object (increment) for cache
            link.increment_clicks()
            self.repository.increment_clicks(short_code)

            # Step 6: Cache on all levels
            self.link_cache.save(link)

            self.logger.info(
                "Redirect successful", code=short_code.value, url=orig_url[:50]
            )

            self.audit_logger.log_url_accessed(link, user_ip, user_agent)

            return orig_url

        except ValueError as e:
            self.logger.error(
                "Invalid short code format", code=short_code_str, error=str(e)
            )
            raise ValueError(f"Invalid short code: {str(e)}")

        except LinkNotFoundError:
            raise

        except Exception as e:
            self.logger.exception(
                "Error during redirect",
                exc_info=str(e),
                short_code=short_code_str,
            )
            raise RuntimeError(f"Failed to redirect: {str(e)}")

    def _audit_and_update_async(
        self, short_code: ShortCode, user_ip: Optional[str], user_agent: Optional[str]
    ) -> None:
        """
        TODO: Replace with proper async task queue (Celery) later.

        Perform audit logging and click increment in a background thread.

        This is a temporary solution to avoid blocking the redirect response.
        In production, this should be replaced with a proper task queue (e.g., Celery).

        The thread:
        - Fetches the link (from cache or repository).
        - Audits the access.
        - Increments click count in repository.
        - Updates the cache with incremented count.
        """
        def task():
            try:
                # Try to get link from cache first (fast)
                link = self.link_cache.get_by_code(short_code)
                if not link:
                    link = self.repository.find_by_code(short_code)
                
                if link:
                    # Audit
                    self.audit_logger.log_url_accessed(link, user_ip, user_agent)
                    
                    # Increment in repository
                    self.repository.increment_clicks(short_code)

                    # Update local link object for cache
                    link.increment_clicks()
                    # Refresh cache with updated link
                    self.link_cache.save(link)

                    self.logger.debug(
                        "Background click increment and audit completed",
                        short_code=short_code.value,
                        new_clicks=link.clicks,
                    )

                else:
                    self.logger.error(
                        "Background task failed: link not found", 
                        code=short_code.value
                    )

            except Exception as e:
                self.logger.error(
                    "Background click increment and audit failed",
                    short_code=short_code.value,
                    error=str(e),
                )
        thread = threading.Thread(target=task)
        thread.daemon = True
        thread.start()
