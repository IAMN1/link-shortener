from dataclasses import dataclass
from typing import Optional

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.health_check import HealthCheck
from link_shortener.application.ports.logging_status import (
    LoggingStatus, LoggingStatusPort,
)
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.use_cases.base_use_case import BaseUseCase


@dataclass
class ServiceHealthStatus:
    """Data object holding the health status of infrastructure components."""
    database: bool
    redis: bool
    task_queue: bool
    rate_limiter: bool = True
    """Whether request limits are currently being enforced."""
    logging: Optional[LoggingStatus] = None
    """State of the logging and audit chains, when a reader is wired in.

    Optional because the health answer predates it and a caller that
    builds this use case without one still gets the rest.
    """

class GetServiceHealthUseCase(BaseUseCase):
    """Check the health of all infrastructure dependencies.

    Takes the same bounded snapshot ``/health`` does. It used to run its own
    checks and cache the result for 15 seconds, so the admin panel and the
    container probe could disagree about the same component for as long as
    that cache lived -- with nothing to tell an operator which of the two
    was out of date. Two surfaces reporting one system have to read it from
    one place.

    The snapshot carries its own time budget, which is what the cache was
    really protecting against; there is nothing left for the cache to buy.
    """

    def __init__(
        self,
        health_check_port: HealthCheck,
        logger: Logger,
        logging_status: Optional[LoggingStatusPort] = None,
    ):
        """
        Args:
            health_check_port: Implementation of HealthCheck.
            logger: Application logger.
        """
        self.health_check = health_check_port
        self.logging_status = logging_status
        self.logger = logger

    def execute(self, context: RequestContext) -> ServiceHealthStatus:
        """
        Execute the health check.

        Args:
            context: Request context (not used for actual checks, only for logging).

        Returns:
            ServiceHealthStatus indicating which components are healthy.
        """
        log = self._get_logger(self.logger, context)
        log.debug("Checking service health")

        state = self.health_check.snapshot()

        return ServiceHealthStatus(
            database=state.database,
            redis=state.cache,
            task_queue=state.task_queue,
            rate_limiter=state.rate_limiter,
            logging=(
                self.logging_status.read() if self.logging_status else None
            ),
        )
