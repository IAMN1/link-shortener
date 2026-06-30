import time
from dataclasses import dataclass

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.health_check import HealthCheck
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.use_cases.base_use_case import BaseUseCase


@dataclass
class ServiceHealthStatus:
    """Data object holding the health status of infrastructure components."""
    database: bool
    redis: bool
    task_queue: bool

class GetServiceHealthUseCase(BaseUseCase):
    """Check the health of all infrastructure dependencies."""

    CACHE_TTL = 15  # seconds

    def __init__(self, health_check_port: HealthCheck, logger: Logger):
        """
        Args:
            health_check_port: Implementation of HealthCheck.
            logger: Application logger.
        """
        self.health_check = health_check_port
        self.logger = logger
        self._cached_result: ServiceHealthStatus | None = None
        self._cache_timestamp: float = 0.0

    def execute(self, context: RequestContext) -> ServiceHealthStatus:
        """
        Execute the health check.

        Args:
            context: Request context (not used for actual checks, only for logging).

        Returns:
            ServiceHealthStatus indicating which components are healthy.
        """
        now = time.time()
        if self._cached_result is not None and (now - self._cache_timestamp) < self.CACHE_TTL:
            return self._cached_result

        log = self._get_logger(self.logger, context)
        log.debug("Checking service health")

        db_ok = self.health_check.check_database()
        cache_ok = self.health_check.check_cache()
        celery_ok = self.health_check.check_task_queue()

        self._cached_result = ServiceHealthStatus(db_ok, cache_ok, celery_ok)
        self._cache_timestamp = now

        return self._cached_result
