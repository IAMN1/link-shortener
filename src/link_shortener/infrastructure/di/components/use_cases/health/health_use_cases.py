from dataclasses import dataclass
from typing import Optional

from link_shortener.application import HealthCheck, Logger, GetServiceHealthUseCase
from link_shortener.application.ports.logging_status import LoggingStatusPort

@dataclass
class HealthUseCasesComponent:
    """
    Provides factory method for the service health use case.

    This component is responsible for creating a fully configured
    ``GetServiceHealthUseCase`` instance, injecting the required
    ``HealthCheck`` port and application ``Logger``.

    Attributes:
        health_check: The infrastructure health check implementation.
        logger: Application logger injected into the use case.
        logging_status: Reader for the logging and audit chains.
    """
    health_check: HealthCheck
    logger: Logger
    logging_status: Optional[LoggingStatusPort] = None

    def get_service_health_use_case(self) -> GetServiceHealthUseCase:
        """
        Return a fully configured ``GetServiceHealthUseCase``.

        Returns:
            A new ``GetServiceHealthUseCase`` instance with the health
            check port and logger wired in.
        """
        return GetServiceHealthUseCase(
            health_check_port=self.health_check,
            logger=self.logger,
            logging_status=self.logging_status,
        )
