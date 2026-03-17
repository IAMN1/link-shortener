from dataclasses import dataclass
import time
from typing import List
from urllib.parse import urlparse


from link_shortener.application import(
    ShortLinkResponse, LinkCache, AuditLogger, Logger
)

from link_shortener.application.context import RequestContext
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import (
    Link, LinkRepository, OriginalUrl, ShortCode, ShorteningPolicy
)


@dataclass
class CreateShortLinkUseCase(BaseUseCase):
    """
    Use case: Create a single short link.

    Steps:
    1. Validate and normalize the input URL via OriginalUrl value object.
    2. Compute the URL hash for deduplication.
    3. Check cache for existing link by hash (fast path).
    4. If not in cache, check repository.
    5. If found, return cached/existing link.
    6. If not found, generate a unique short code (handling collisions).
    7. Create a new Link entity and save it to repository and cache.
    8. Audit the creation event.
    """

    repository: LinkRepository
    cache: LinkCache
    shortening_policy: ShorteningPolicy
    base_url: str
    logger: Logger
    audit_logger: AuditLogger
    allowed_schemes: List[str]
    max_collision_attempts: int = 5

    def execute(
        self, url: str, context: RequestContext) -> ShortLinkResponse:
        """
        Execute the create short link use case.

        Args:
            url: The original URL to shorten.
            context: Request context with client metadata.

        Returns:
            ShortLinkResponse with link details.

        Raises:
            ValueError: If the URL is invalid.
            RuntimeError: If code generation fails after max attempts.
        """

        # Привязка контекста к логгеру
        log = self._get_logger(self.logger, context)
        start_time = time.perf_counter()
        log.info("Starting short link creation", url=url[:50])

        try:
            
            parsed = urlparse(url)
            if parsed.scheme not in self.allowed_schemes:
                raise ValueError(
                    f"Scheme '{parsed.scheme}' is not allowed. "
                    f"Allowed schemes: {', '.join(self.allowed_schemes)}"
                )

            # Step 1: Create value object – validation happens here
            original_url = OriginalUrl(url)

            # Step 2: Compute hash for deduplication
            url_hash = self.shortening_policy.calculate_hash(original_url)

            # Step 3: Check cache
            cached_link = self.cache.get_by_hash(url_hash)
            if cached_link:

                log.debug("Cache hit", hash=url_hash.value[:10])

                return self._build_response(
                    cached_link, from_cache=True, is_new=False
                )

            # Step 4: Check repository
            existing_link = self.repository.find_by_hash(url_hash)
            if existing_link:

                log.debug("Found in repository", hash=url_hash.value[:10])
                
                # Cache it for future requests
                self.cache.save(existing_link)
                return self._build_response(
                    existing_link, from_cache=False, is_new=False
                )

            # Step 5: Generate unique short code
            short_code = self._generate_unique_code(original_url, log)

            # Step 6: Create domain entity
            new_link = Link.create(
                url_hash=url_hash, short_code=short_code, original_url=original_url
            )

            # Step 7: Save to repository and cache
            saved_link = self.repository.save(new_link)
            self.cache.save(saved_link)

            log.info(
                "Short link created successfully", short_code=short_code.value
            )
            
            self.audit_logger.log_url_created(saved_link, context)

            return self._build_response(
                saved_link, from_cache=False, is_new=True
            )
        except ValueError as e:
            log.error("Validation failed", error=str(e))
            raise ValueError(f"Invalid URL {str(e)}")

        except Exception as e:
            log.error("Error creating short link", error=str(e))
            raise e
        finally:
            duration = time.perf_counter() - start_time
            log.debug("Execution time", duration_ms=round(duration * 1000, 2))

    def _generate_unique_code(self, original_url: OriginalUrl, log: Logger) -> ShortCode:
        """
        Generate a short code that is unique in the repository.

        Attempts up to max_collision_attempts, each time adding a salt
        to the input to produce a different code if collision occurs.

        Args:
            original_url: The original URL value object.
            log: Logger with bound context.

        Returns:
            Unique ShortCode.

        Raises:
            RuntimeError: If a unique code cannot be generated after max attempts.
        """
        
        for attempt in range(self.max_collision_attempts):

            code = self.shortening_policy.generate_unique_code(original_url, attempt)

            existing = self.repository.find_by_code(code)
            if (
                not existing
                or existing.url_hash
                == self.shortening_policy.calculate_hash(original_url)
            ):
                # No collision, or collision with the same URL 
                # (shouldn't happen, but safe)
                return code

            log.debug("Code collision, retrying", attempt=attempt + 1, code=code.value)

        raise RuntimeError(
            "Failed to generate unique short code after multiple attempts"
        )
    
    def _build_response(self, link: Link, from_cache: bool, is_new: bool) -> ShortLinkResponse:
        """Build a ShortLinkResponse DTO from a Link entity."""
        return ShortLinkResponse.from_link(
            link, self.base_url, is_new=is_new, from_cache=from_cache
        )
