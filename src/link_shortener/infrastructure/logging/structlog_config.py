from typing import List

import structlog
from structlog.typing import Processor

from link_shortener.infrastructure.logging.logging_settings import LoggingSettings


def _replace_logger_name_with_module(logger, method_name, event_dict):
    """
    Processor that replaces the logger name with the module name if present.

    This allows the module name (added by the application) to appear in
    the ``logger`` key, which is then formatted by the renderer.
    """
    if 'module' in event_dict:
        event_dict['logger'] = event_dict.pop('module')
    return event_dict

def configure_structlog(settings: LoggingSettings):
    """
    Configure structlog with the application's processor chain.

    Does not add a final renderer; rendering is handled by the
    ``ProcessorFormatter`` that is attached to each handler individually.

    Args:
        settings: ``LoggingSettings`` instance.
    """

    processors: List[Processor] = [
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt=settings.log_date_format, utc=True),
        _replace_logger_name_with_module,
        structlog.processors.StackInfoRenderer(),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,

    ]

    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
