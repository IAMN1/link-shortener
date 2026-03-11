from dataclasses import dataclass


from link_shortener.application import (
    ExtendedLinkInfoResponse, ShortLinkResponse, LinkCache, Logger
)

from link_shortener.domain import LinkNotFoundError, LinkRepository, ShortCode


@dataclass
class GetLinkInfoUseCase:
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

    def execute(self, short_code_str: str) -> ShortLinkResponse:
        """
        Execute the get link info use case.

        Args:
            short_code_str: Short code as string.

        Returns:
            ShortLinkResponse with link details.

        Raises:
            LinkNotFoundError: If link not found.
            ValueError: If short code format is invalid.
        """
        try:
            # Step 1: Validate short code
            short_code = ShortCode(short_code_str)

            self.logger.debug("Getting link info for", short_code=short_code.value)

            # Step 2: Check cache
            cached_link = self.cache.get_by_code(short_code)
            if cached_link:

                self.logger.info("Cache hit for code", code=short_code.value)

                return ShortLinkResponse.from_link(
                    cached_link, base_url=self.base_url, is_new=False, from_cache=True
                )

            # Step 3: Query repository
            link = self.repository.find_by_code(short_code)
            if not link:
                self.logger.warning("Link not found", code=short_code.value)
                raise LinkNotFoundError(short_code_str)

            # Step 4: Cache for future requests
            self.cache.save(link)

            self.logger.info("Found in repository", short_code=short_code.value)

            # Step 5: Return response
            return ShortLinkResponse.from_link(link, self.base_url, from_cache=False)

        except ValueError as e:
            self.logger.error("Invalid short code format", short_code=short_code_str)
            raise ValueError(f"Invalid short code: {str(e)}")

        except LinkNotFoundError:
            raise

        except Exception as e:
            self.logger.exception(
                "Error getting link info", short_code=short_code_str, exc_info=str(e)
            )
            raise


@dataclass
class GetExtendLinkInfoUseCase:
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

    def execute(self, short_code_str: str) -> ExtendedLinkInfoResponse:
        """
        Execute the extended info use case.

        Args:
            short_code_str: Short code as string.

        Returns:
            ExtendedLinkInfoResponse with metrics.

        Raises:
            LinkNotFoundError: If link not found.
            ValueError: If short code format is invalid.
        """
        try:

            short_code = ShortCode(short_code_str)

            self.logger.debug(
                "Getting extend link info for", short_code=short_code.value
            )

            # Check cache first
            cached_link = self.cache.get_by_code(short_code)
            if cached_link:
                self.logger.info("Cache hit for code", code=short_code.value)
                return ExtendedLinkInfoResponse.from_link(
                    cached_link, 
                    base_url=self.base_url,
                    popular_threshold=self.popular_threshold,
                    recent_days=self.recent_days
                )

            # Query repository
            link = self.repository.find_by_code(short_code)
            if not link:
                self.logger.warning("Link not found", code=short_code.value)
                raise LinkNotFoundError(short_code_str)

            # Cache for future
            self.cache.save(link)

            self.logger.info("Found in repository", short_code=short_code.value)

            return ExtendedLinkInfoResponse.from_link(
                link, 
                base_url=self.base_url,
                popular_threshold=self.popular_threshold,
                recent_days=self.recent_days
            )

        except ValueError as e:
            self.logger.error("Invalid short code format", short_code=short_code_str)
            raise ValueError(f"Invalid short code: {str(e)}")

        except LinkNotFoundError:
            raise

        except Exception as e:
            self.logger.error(
                "Error getting extended link info",
                short_code=short_code_str,
                error=str(e),
            )
            raise
