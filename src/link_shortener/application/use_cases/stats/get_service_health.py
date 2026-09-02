from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

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
    database_schema: bool
    """Whether the database reached holds this application's tables.

    Beside the boolean above, because that one cannot say it: a database
    the migration never reached answers every connectivity probe and
    serves nothing. Carried here so the admin surfaces show the same
    three states ``/health`` and ``flask maintenance health`` show,
    rather than a green Database over a service answering 500.
    """
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
    task_queue_configured: bool = True
    """Whether there is a broker behind the queue at all.

    The sibling of ``cache_configured`` above, and it was missing for the
    same reason nothing noticed: ``task_queue`` alone reads "ok" both when
    the workers answer and when the work is done in the request.
    """
    rate_limiter: bool = True
    """Whether request limits are currently being enforced."""
    components: Dict[str, str] = field(default_factory=dict)
    """The per-component verdict, in the snapshot's vocabulary.

    Beside the booleans rather than instead of them, and it is the field
    the health page reads. The booleans say what was measured; deciding
    what they mean was being done a fourth time in JavaScript, which is
    how that page came to call a queue that does not exist "ok" and a
    cache keeping entries "absent". The judgement is the snapshot's, and
    every surface now renders the same one.
    """
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

@dataclass
class GetServiceHealthUseCase(BaseUseCase):
    """Check the health of all infrastructure dependencies.

    Takes the same bounded snapshot ``/health`` does, rather than running
    checks of its own: two surfaces reporting one system have to read it
    from one place, or the admin panel and the container probe can
    disagree about the same component with nothing to say which is out of
    date. The snapshot carries its own time budget, so there is nothing
    left for a cache to buy here.

    Declared as dataclass fields like every other use case here. It was
    the one that took its dependencies through ``__init__`` -- which reads
    the same to a caller and differently to anybody sweeping the layer,
    and `architecture.md` states the rule for all of them.

    Attributes:
        health_check_port: The bounded snapshot every surface reads from.
        logger: Application logger.
        logging_status: Reader for the state of the logging and audit
            chains. Optional because the health answer predates it, and a
            caller that builds this without one still gets the rest.
    """

    health_check_port: HealthCheck
    logger: Logger
    logging_status: Optional[LoggingStatusPort] = None

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

        state = self.health_check_port.snapshot()

        return ServiceHealthStatus(
            database=state.database,
            database_schema=state.database_schema,
            redis=state.cache,
            cache_configured=state.cache_configured,
            task_queue_configured=state.task_queue_configured,
            task_queue=state.task_queue,
            rate_limiter=state.rate_limiter,
            components=state.component_states(),
            timed_out=state.timed_out,
            logging=(
                self.logging_status.read() if self.logging_status else None
            ),
        )
