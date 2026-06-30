from dataclasses import dataclass
import time
from typing import Callable, List


from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.link import ShortLinkResponse
from link_shortener.application.ports.cache.link_cache import LinkCache
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import (
    Link, OriginalUrl, ShortCode, 
    HashCalculator, CodeGenerator, OwnerID,
    ValidationError, CodeGenerationError, GuestLinkLimitExceededError
)


@dataclass
class CreateShortLinkUseCase(BaseUseCase):
    """
    Use case for creating a single short link.

    Orchestrates URL validation, deduplication, code generation, persistence and caching.

    Attributes:
        uow_factory: Callable factory for creating Unit of Work instances.
        cache: Link cache implementation for fast lookups.
        hash_calculator: Strategy for computing URL hashes.
        code_generator: Strategy for generating short codes.
        base_url: Base URL of the service for building short URLs.
        logger: Application logger.
        audit_logger: Audit logger for significant events.
        allowed_schemes: List of allowed URL schemes (e.g., ['http', 'https']).
        guest_link_limit: Max number of guest links per window.
        guest_link_window_days: Time window in days for guest link counting.
        default_guest_ttl_seconds: Default TTL for gues-created links.
        max_collision_attempts: Maximum tries to generate a unique code.
    """

    uow_factory: Callable[[], UnitOfWork]
    cache: LinkCache
    hash_calculator: HashCalculator
    code_generator: CodeGenerator
    base_url: str
    logger: Logger
    audit_logger: AuditLogger
    allowed_schemes: List[str]
    guest_link_limit: int
    guest_link_window_days: int
    default_guest_ttl_seconds: int
    max_collision_attempts: int = 5

    def execute(
        self, url: str, context: RequestContext, ttl_seconds: int = 0) -> ShortLinkResponse:
        """
        Execute the create short link use case.

        Args:
            url: The original URL to shorten.
            context: Request context with client metadata.
            ttl_seconds: Time-to-live in seconds (0 = forever).

        Returns:
            ShortLinkResponse DTO with link details.

        Raises:
            ValidationError: If the URL is invalid or scheme not allowed.
            GuestLinkLimitExceededError: If the guest link limit is exceeded.
            CodeGenerationError: If code generation fails after max attempts.
        """

        # Bind request context to the logger.
        log = self._get_logger(self.logger, context)
        audit = self._get_audit_logger(self.audit_logger, context)

        start_time = time.perf_counter()
        log.info("Starting short link creation", url=url[:50])

        try:

            # ---- 1. Validate URL via value object ----------------
            original_url = OriginalUrl(url, allowed_schemes=tuple(self.allowed_schemes))

            # ---- 2. Compute hash for deduplication ---------------
            url_hash = self.hash_calculator.calculate(original_url)

            # ---- Guest limit & TTL enforcement -------------------
            guest_id = None
            if not context.current_user:
                guest_id = context.remote_addr
            
                with self.uow_factory() as uow:
                    count = uow.links.count_guest_links_by_identifier(
                        guest_id, self.guest_link_window_days
                    )
                if count >= self.guest_link_limit:
                    raise GuestLinkLimitExceededError(
                        f"Guest link limit of {self.guest_link_limit} exceeded."
                    )
                # For guests, apply a default TTL of 7 days if none specified.
                if ttl_seconds == 0:
                    ttl_seconds = self.default_guest_ttl_seconds

            # ---- 3. Check cache (fast path) ----------------------
            cached_link = self.cache.get_by_hash(url_hash)
            if cached_link:

                log.debug("Cache hit", hash=url_hash.value[:10])

                return self._build_response(
                    cached_link, from_cache=True, is_new=False
                )

            # ---- 4. Check repository -----------------------------
            with self.uow_factory() as uow:
                existing_link = uow.links.find_by_hash(url_hash)
                if existing_link:

                    log.debug("Found in repository", hash=url_hash.value[:10])
                
                    # Cache for future requests
                    self.cache.save(existing_link)
                    return self._build_response(existing_link, from_cache=False, is_new=False)

                # -- 5. Generate unique short code -----------------
                short_code = self._generate_unique_code(original_url, uow, log)

                # -- 6. Create domain entity -----------------------
                owner = context.current_user.id if context.current_user else None
                owner_id_vo = OwnerID(owner)
                new_link = Link.create(
                    url_hash=url_hash,
                    short_code=short_code,
                    original_url=original_url,
                    owner=owner_id_vo,
                    guest_identifier=guest_id,
                    ttl_seconds=ttl_seconds,
                )

                saved_link = uow.links.save(new_link)
                uow.commit()

            # ---- 7. Cache new link & audit -----------------------
            self.cache.save(saved_link)

            log.info("Short link created successfully", short_code=short_code.value)
            
            audit.log_url_created(short_code=saved_link.short_code.value, original_url=saved_link.original_url.value)

            return self._build_response(saved_link, from_cache=False, is_new=True)
        except ValueError as e:
            log.error("Validation failed", error=str(e))
            raise ValidationError(f"Invalid URL {str(e)}")
        except Exception as e:
            log.error("Error creating short link", error=str(e))
            raise e
        finally:
            duration = time.perf_counter() - start_time
            log.debug("Execution time", duration_ms=round(duration * 1000, 2))



    def _generate_unique_code(self, original_url: OriginalUrl, uow: UnitOfWork, log: Logger) -> ShortCode:
        """
        Generate a unique short code, retrying on collisions.

        Args:
            original_url: The validated original URL.
            uow: Active Unit of Work for checking existence.
            log: Logger instance.

        Returns:
            A unique ShortCode value object.

        Raises:
            CodeGenerationError: If no unique code can be generated after max attempts.
        """
        for attempt in range(self.max_collision_attempts):
            code = self.code_generator.generate_unique(original_url, attempt)
            if not uow.links.find_by_code(code):
                return code

            log.debug("Code collision, retrying", attempt=attempt + 1, code=code.value)
        raise CodeGenerationError()


    def _build_response(self, link: Link, from_cache: bool, is_new: bool) -> ShortLinkResponse:
        """
        Build a ShortLinkResponse DTO from a domain Link entity.

        Args:
            link: The domain Link object.
            from_cache: Whether the data came from cache.
            is_new: Whether the link was just created.

        Returns:
            ShortLinkResponse DTO ready for serialization.
        """
        return ShortLinkResponse.from_link(link, self.base_url, is_new=is_new, from_cache=from_cache)
