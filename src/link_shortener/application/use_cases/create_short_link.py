from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urlparse


from link_shortener.application import(
    ShortLinkResponse, LinkCache, AuditLogger, Logger
)

from link_shortener.domain import (
    Link, LinkRepository, OriginalUrl, ShortCode, ShorteningPolicy
)


@dataclass
class CreateShortLinkUseCase:
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
        self, url: str, user_ip: Optional[str] = None, user_agent: Optional[str] = None
    ) -> ShortLinkResponse:
        """
        Execute the create short link use case.

        Args:
            url: The original URL to shorten.
            user_ip: Client IP address (for audit). Optional.
            user_agent: Client User-Agent (for audit). Optional.

        Returns:
            ShortLinkResponse with link details.

        Raises:
            ValueError: If the URL is invalid.
            RuntimeError: If code generation fails after max attempts.
        """
        try:
            
            parsed = urlparse(url)
            if parsed.scheme not in self.allowed_schemes:
                raise ValueError(
                    f"Scheme '{parsed.scheme}' is not allowed. "
                    f"Allowed schemes: {', '.join(self.allowed_schemes)}"
                )

            # Step 1: Create value object – validation happens here
            original_url = OriginalUrl(url)

            self.logger.info(
                "Starting short link creation", url=original_url.value[:50]
            )

            # Step 2: Compute hash for deduplication
            url_hash = self.shortening_policy.calculate_hash(original_url)

            # Step 3: Check cache
            cached_link = self.cache.get_by_hash(url_hash)
            if cached_link:
                self.logger.debug(
                    "Cache hit for Url,", url=url[:50], hash=url_hash.value[:10]
                )
                return ShortLinkResponse.from_link(
                    cached_link, base_url=self.base_url, from_cache=True
                )

            # Step 4: Check repository
            existing_link = self.repository.find_by_hash(url_hash)
            if existing_link:
                self.logger.debug("Found in repository", hash=url_hash.value[:10])
                
                # Cache it for future requests
                self.cache.save(existing_link)
                return ShortLinkResponse.from_link(
                    link=existing_link,
                    base_url=self.base_url,
                    is_new=False,
                    from_cache=False,
                )

            # Step 5: Generate unique short code
            short_code = self._generate_unique_code(original_url)

            # Step 6: Create domain entity
            new_link = Link.create(
                url_hash=url_hash, short_code=short_code, original_url=original_url
            )

            # Step 7: Save to repository and cache
            saved_link = self.repository.save(new_link)
            self.cache.save(saved_link)

            self.logger.info(
                "Short link created successfully", short_code=short_code.value
            )
            
            self.audit_logger.log_url_created(saved_link, user_ip=user_ip, user_agent=user_agent)

            return ShortLinkResponse.from_link(
                link=saved_link, base_url=self.base_url, is_new=True
            )
        except ValueError as e:
            self.logger.error("Validation failed", url=url[:50], error=str(e))
            raise ValueError(f"Invalid URL {str(e)}")

        except Exception as e:
            self.logger.error("Error creating short link", error=str(e))
            raise e

    def _generate_unique_code(self, original_url: OriginalUrl) -> ShortCode:
        """
        Generate a short code that is unique in the repository.

        Attempts up to max_collision_attempts, each time adding a salt
        to the input to produce a different code if collision occurs.

        Args:
            original_url: The original URL value object.

        Returns:
            Unique ShortCode.

        Raises:
            RuntimeError: If a unique code cannot be generated after max attempts.
        """
        attempt = 0
        while attempt < self.max_collision_attempts:

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

            # Колизия
            attempt += 1
        raise RuntimeError(
            "Failed to generate unique short code after multiple attempts"
        )
