from dataclasses import dataclass
import time


from link_shortener.application import (
    ExtendedLinkInfoResponse, ShortLinkResponse, LinkCache, Logger
)

from link_shortener.application.context import RequestContext
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import LinkNotFoundError, LinkRepository, ShortCode


@dataclass
class GetLinkInfoUseCase(BaseUseCase):
    """
    Use case: Retrieve basic information about a short link.

    Steps:
    1. Validate the short code via ShortCode value object.
    2. Check cache for the link by code.
    3. If not in cache, query repository.
    4. If found, cache it and return response.
    5. If not found, raise LinkNotFoundError.
    """

    repository: LinkRepository
    cache: LinkCache
    base_url: str
    logger: Logger

    def execute(self, short_code_str: str, context: RequestContext) -> ShortLinkResponse:
        """
        Execute the get link info use case.

        Args:
            short_code_str: Short code as string.
            context: Request context with client metadata.

        Returns:
            ShortLinkResponse with link details.

        Raises:
            LinkNotFoundError: If link not found.
            ValueError: If short code format is invalid.
        """

        log = self._get_logger(self.logger, context)
        start_time = time.perf_counter()
        log.debug("Getting link info", short_code=short_code_str)

        try:
            # Step 1: Validate short code
            short_code = ShortCode(short_code_str)

            # Step 2: Check cache
            cached_link = self.cache.get_by_code(short_code)
            if cached_link:

                log.info("Cache hit", code=short_code.value)

                return ShortLinkResponse.from_link(
                    cached_link, base_url=self.base_url, is_new=False, from_cache=True
                )

            # Step 3: Query repository
            link = self.repository.find_by_code(short_code)
            if not link:
                log.warning("Link not found", code=short_code.value)
                raise LinkNotFoundError(short_code_str)

            # Step 4: Cache for future requests
            self.cache.save(link)

            log.info("Found in repository", short_code=short_code.value)

            # Step 5: Return response
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


@dataclass
class GetExtendLinkInfoUseCase(BaseUseCase):
    """
    Use case: Retrieve extended information about a short link,
    including derived metrics like popularity, age, clicks per day.
    """

    repository: LinkRepository
    cache: LinkCache
    base_url: str
    logger: Logger
    popular_threshold: int
    recent_days: int

    def execute(self, short_code_str: str, context: RequestContext) -> ExtendedLinkInfoResponse:
        """
        Execute the extended info use case.

        Args:
            short_code_str: Short code as string.
            context: Request context with client metadata.

        Returns:
            ExtendedLinkInfoResponse with metrics.

        Raises:
            LinkNotFoundError: If link not found.
            ValueError: If short code format is invalid.
        """
        log = self._get_logger(self.logger, context)
        start_time = time.perf_counter()
        log.debug("Getting extend link info", short_code=short_code_str)

        try:

            short_code = ShortCode(short_code_str)

            # Check cache first
            cached_link = self.cache.get_by_code(short_code)
            if cached_link:
                log.info("Cache hit for code", code=short_code.value)
                return ExtendedLinkInfoResponse.from_link(
                    cached_link, 
                    base_url=self.base_url,
                    popular_threshold=self.popular_threshold,
                    recent_days=self.recent_days
                )

            # Query repository
            link = self.repository.find_by_code(short_code)
            if not link:
                log.warning("Link not found", code=short_code.value)
                raise LinkNotFoundError(short_code_str)

            # Cache for future
            self.cache.save(link)

            log.info("Found in repository", short_code=short_code.value)

            return ExtendedLinkInfoResponse.from_link(
                link, 
                base_url=self.base_url,
                popular_threshold=self.popular_threshold,
                recent_days=self.recent_days
            )

        except ValueError as e:
            log.error("Invalid short code format", short_code=short_code_str)
            raise ValueError(f"Invalid short code: {str(e)}")

        except LinkNotFoundError:
            raise

        except Exception as e:
            log.error(
                "Error getting extended link info",
                short_code=short_code_str,
                error=str(e),
            )
            raise
        finally:
            duration = time.perf_counter() - start_time
            log.debug("Execution time", duration_ms=round(duration * 1000, 2))
