from dataclasses import dataclass, field
from typing import Optional, Tuple

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
    cache_configured: bool
    """Whether a cache backend is configured at all.

    Carried because ``redis`` alone cannot say it. A cache nobody
    configured answers every probe well -- it has nothing to be down --
    so the boolean beside this one is ``True`` on a deployment running
    ``REDIS_ENABLED=false``, and the admin surfaces showed a row reading
    "Redis: answering" over a service with no Redis. The other two
    surfaces already told the two apart: ``/health`` says ``disabled``
    and ``flask maintenance health`` says ``not configured``, both off
    this same field on the snapshot, which stopped here.
    """
    task_queue: bool
    rate_limiter: bool = True
    """Whether request limits are currently being enforced."""
    timed_out: Tuple[str, ...] = field(default=())
    """Components that did not answer within the snapshot's budget.

    Reported unhealthy either way, and kept apart for the reason
    ``HealthSnapshot`` states: "did not answer in time" is not the
    finding "answered no" is, and only one of them says which dependency
    is hanging. It reached ``/health`` and the shell command and stopped
    here, so the surface an operator actually watches was the one that
    could not tell them apart.
    """
    logging: Optional[LoggingStatus] = None
    """State of the logging and audit chains, when a reader is wired in.

    Optional because the health answer predates it and a caller that
    builds this use case without one still gets the rest.
    """

class GetServiceHealthUseCase(BaseUseCase):
    """Check the health of all infrastructure dependencies.

    Takes the same bounded snapshot ``/health`` does, rather than running
    checks of its own: two surfaces reporting one system have to read it
    from one place, or the admin panel and the container probe can
    disagree about the same component with nothing to say which is out of
    date. The snapshot carries its own time budget, so there is nothing
    left for a cache to buy here.
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
            cache_configured=state.cache_configured,
            task_queue=state.task_queue,
            rate_limiter=state.rate_limiter,
            timed_out=state.timed_out,
            logging=(
                self.logging_status.read() if self.logging_status else None
            ),
        )
