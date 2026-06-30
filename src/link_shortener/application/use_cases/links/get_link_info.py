from dataclasses import dataclass
import time
from typing import Callable

from link_shortener.application import (
    ShortLinkResponse, LinkCache, Logger
)

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import (
    LinkNotFoundError, ShortCode
)

@dataclass
class GetLinkInfoUseCase(BaseUseCase):
    """
    Retrieve basic information about a short link.

    Flow:
        1. Validate the short code via domain value object.
        2. Check L2 cache (full link) by short code.
        3. Cache miss -> query repository (read-only).
        4. Populate L2 cache on DB hit before returning.

    Attributes:
        uow_factory: Callable that returns a new Unit of Work instance.
        cache: Implementation of the link cache (L2).
        base_url: Base URL of the service for constructing short URLs.
        logger: Application logger.
        auth_service: Authorization service for permission checks.
    """

    uow_factory: Callable[[], UnitOfWork]
    cache: LinkCache
    base_url: str
    logger: Logger

    def execute(self, short_code_str: str, context: RequestContext) -> ShortLinkResponse:
        """Execute the use case.

        Args:
            short_code_str: Short code as a plain string.
            context: Request context containing authenticated user info.

        Returns:
            ShortLinkResponse with link details.

        Raises:
            LinkNotFoundError: If the short code does not exist.
            ValueError: If the short code format is invalid.
            DomainError: If the requester is not authorized to view the link.
        """
        log = self._get_logger(self.logger, context)
        start_time = time.perf_counter()
        log.debug("Getting link info", short_code=short_code_str)

        try:
            # Step 1: Validate short code via domain value object
            short_code = ShortCode(short_code_str)

            # Step 2: L2 cache lookup
            cached_link = self.cache.get_by_code(short_code)
            if cached_link:
                log.info("Cache hit", code=short_code.value)
                return ShortLinkResponse.from_link(
                    cached_link, base_url=self.base_url, is_new=False, from_cache=True
                )

            # Step 3: Repository lookup (read‑only)
            with self.uow_factory(read_only=True) as uow:
                link = uow.links.find_by_code(short_code)
                if not link:
                    log.warning("Link not found", code=short_code.value)
                    raise LinkNotFoundError(short_code_str)

            # Step 4: Cache the link for future requests
            self.cache.save(link)

            log.info("Found in repository", short_code=short_code.value)
            return ShortLinkResponse.from_link(link, self.base_url, from_cache=False)

        except ValueError as e:
            log.error("Invalid short code format", short_code=short_code_str)
            raise ValueError(f"Invalid short code: {str(e)}")

        except LinkNotFoundError:
            raise

        except Exception as e:
            log.exception(
                "Error getting link info", short_code=short_code_str, exc_info=str(e)
            )
            raise
        finally:
            duration = time.perf_counter() - start_time
            log.debug("Execution time", duration_ms=round(duration * 1000, 2))
