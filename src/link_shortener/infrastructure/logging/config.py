import structlog
from link_shortener.infrastructure.logging.settings import LoggingSettings


def _replace_logger_name_with_module(logger, method_name, event_dict):
    """
    Processor that replaces the logger name with the module name if present.

    This allows us to show the module name in square brackets instead of the
    global logger name. It looks for a key 'module' in the event_dict and,
    if found, moves it to 'logger'.

    Args:
        logger: The logger instance.
        method_name: The logging method name (e.g., 'info').
        event_dict: The current event dictionary.

    Returns:
        The modified event dictionary.
    """
    if 'module' in event_dict:
        event_dict['logger'] = event_dict.pop('module')
    return event_dict

def configure_structlog(settings: LoggingSettings):
    """
    Set up structlog with processors and renderer based on settings.

    This configuration does not include a final renderer – it only adds
    processors that enrich the event dictionary. The actual rendering
    is handled by ProcessorFormatter in the individual handlers.

    Args:
        settings: LoggingSettings object.
    """

    processors = [
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
