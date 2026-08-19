from typing import List

import structlog
from structlog.typing import Processor

from link_shortener.infrastructure.logging.logging_settings import LoggingSettings
from link_shortener.infrastructure.logging.utils import UTC_SECONDS


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
        # The same stamp the standard chain writes, and from the same
        # constant: this side was already UTC while the other was not, and
        # the pair have to agree or a reader cannot tell one journal's
        # moment from the other's. ``log_date_format`` is not consulted
        # here: it dresses the console line of the standard chain, which
        # has a formatter of its own, and this stamp is read by a program.
        # This chain's console renders over these same processors, so its
        # line carries this stamp too.
        structlog.processors.TimeStamper(fmt=UTC_SECONDS, utc=True),
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
