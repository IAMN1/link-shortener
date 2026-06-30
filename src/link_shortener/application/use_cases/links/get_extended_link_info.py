from dataclasses import dataclass
import time
from typing import Callable

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.link import ExtendedLinkInfoResponse
from link_shortener.application.ports.cache.link_cache import LinkCache
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import LinkNotFoundError, ShortCode


@dataclass
class GetExtendedLinkInfoUseCase(BaseUseCase):
    """
    Retrieve extended information including popularity, age, and clicks per day.

    Flow is similar to GetLinkInfoUseCase but produces additional derived metrics.
    """

    uow_factory: Callable[[], UnitOfWork]
    cache: LinkCache
    base_url: str
    logger: Logger
    popular_threshold: int
    recent_days: int

    def execute(self, short_code_str: str, context: RequestContext) -> ExtendedLinkInfoResponse:
        """
        Execute the use case.

        Args:
            short_code_str: Short code as string.
            context: Request context.

        Returns:
            ExtendedLinkInfoResponse with metrics.

        Raises:
            LinkNotFoundError: If link not found.
            ValueError: If short code format is invalid.
            DomainError: If the user is not authorised.
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
            with self.uow_factory(read_only=True) as uow:
                link = uow.links.find_by_code(short_code)
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
