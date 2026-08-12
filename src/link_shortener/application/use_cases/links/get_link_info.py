from dataclasses import dataclass
import time
from typing import Callable

from link_shortener.application import (
    ShortLinkResponse, Logger
)

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import (
    LinkExpiredError, LinkNotFoundError
)

@dataclass
class GetLinkInfoUseCase(BaseUseCase):
    """
    Retrieve basic information about a short link.

    Flow:
        1. Validate the short code via domain value object.
        2. Query the repository (read-only) -- it is the authority here.
        3. Refuse an expired link the way the redirect does.

    This use case does not touch the cache at all, which is a deliberate
    departure from the redirect.

    It does not *read* it because a cached entry says a link existed when
    the entry was written, cannot say whether it still does, and that is
    exactly the question this endpoint answers -- an entry that outlived its
    row served ``200`` with a click count for a link the database no longer
    had. The create path solved the same problem with a confirming read
    (``create_short_link._confirm``), but there the cache earns its keep by
    resolving a hash to a code before the row is fetched. Here the code is
    the request, so confirming a hit and simply reading the row are the same
    query -- and reading the row cannot disagree with itself.

    It does not *write* it because the write would land after the
    transaction closes, where it can reappear behind a concurrent deletion
    that has already invalidated the entry.

    The redirect keeps its cache: it is the hot path, it warms both levels
    from its own repository hit, and this endpoint is rate-limited to a
    hundred requests a minute.

    Attributes:
        uow_factory: Callable that returns a new Unit of Work instance.
        base_url: Base URL of the service for constructing short URLs.
        logger: Application logger.
    """

    uow_factory: Callable[[], UnitOfWork]
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
            LinkExpiredError: If the link exists but has expired.
            ValueError: If the short code format is invalid.
            DomainError: If the requester is not authorized to view the link.
        """
        log = self._get_logger(self.logger, context)
        start_time = time.perf_counter()
        log.debug("Getting link info", short_code=short_code_str)

        try:
            # Step 1: Read the code, or answer that no link carries it
            short_code = self._code_to_look_up(short_code_str)

            # Step 2: Repository lookup (read-only)
            with self.uow_factory(read_only=True) as uow:
                link = uow.links.find_by_code(short_code)
                if not link:
                    log.warning("Link not found", code=short_code.value)
                    raise LinkNotFoundError(short_code_str)

                # Step 3: An expired link is gone, and the redirect already
                # says so with 410. Reporting it here as a healthy link left
                # the two paths disagreeing about the same code.
                if link.is_expired():
                    log.info("Link expired", short_code=short_code.value)
                    raise LinkExpiredError(short_code.value)

            # Nothing is written to the cache here. The write would land
            # after this transaction closes, and a DELETE that ran in
            # between has already done its invalidating -- so the entry
            # reappears behind the deletion and the redirect goes on serving
            # a link the API reports as gone, for as long as CACHE_LINK_TTL
            # (an hour, in production). Reproduced over plain HTTP: eight
            # readers against one deleter, one resurrection per forty
            # attempts.
            #
            # This path has nothing to gain from warming it anyway: it never
            # reads the cache, and the redirect warms both levels from its
            # own repository hit. Refusing to write is not a workaround for
            # the race -- it removes this path from it.

            log.info("Found in repository", short_code=short_code.value)
            return ShortLinkResponse.from_link(link, self.base_url, from_cache=False)

        except ValueError as e:
            log.error("Invalid short code format", short_code=short_code_str)
            raise ValueError(f"Invalid short code: {str(e)}")

        except (LinkNotFoundError, LinkExpiredError):
            raise

        except Exception as e:
            log.exception(
                "Error getting link info", short_code=short_code_str, exc_info=str(e)
            )
            raise
        finally:
            duration = time.perf_counter() - start_time
            log.debug("Execution time", duration_ms=round(duration * 1000, 2))
