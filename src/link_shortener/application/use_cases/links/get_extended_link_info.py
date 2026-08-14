from dataclasses import dataclass
import time

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.link import ExtendedLinkInfoResponse
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import LinkExpiredError, LinkNotFoundError


@dataclass
class GetExtendedLinkInfoUseCase(BaseUseCase):
    """
    Retrieve extended information including popularity, age, and clicks per day.

    Flow is the same as GetLinkInfoUseCase -- including its reasons for
    leaving the cache alone in both directions -- but produces additional
    derived metrics.
    """

    uow_factory: UnitOfWorkFactory
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
            LinkNotFoundError: If no link carries this code -- including a
                string the format rules refuse, which is a code no link can
                carry. ``_code_to_look_up`` decides that, so no
                ``ValueError`` reaches a caller for a malformed code.
            LinkExpiredError: If the link exists but has expired.
            DomainError: If the user is not authorised.
        """
        log = self._get_logger(self.logger, context)
        start_time = time.perf_counter()
        log.debug("Getting extend link info", short_code=short_code_str)

        try:

            short_code = self._code_to_look_up(short_code_str)

            # Query repository -- the authority for whether the link is
            # still there. This use case has no cache to consult at all:
            # the field was dropped in 26a9339, and the comment that stood
            # here outlived it, still saying the cache was written on this
            # path while the line below said it deliberately was not.
            with self.uow_factory(read_only=True) as uow:
                link = uow.links.find_by_code(short_code)
                if not link:
                    log.warning("Link not found", code=short_code.value)
                    raise LinkNotFoundError(short_code_str)

                if link.is_expired():
                    log.info("Link expired", short_code=short_code.value)
                    raise LinkExpiredError(short_code.value)

            # Deliberately not cached -- see GetLinkInfoUseCase for why a
            # write here reappears behind a concurrent deletion.

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

        except (LinkNotFoundError, LinkExpiredError):
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
