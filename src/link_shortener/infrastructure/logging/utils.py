
import structlog


def get_structlog_logger(name: str = None) -> structlog.BoundLogger:
    """
    Get a structlog logger with the given name.
    This is intended for infrastructure code that needs a structlog logger directly
    (e.g., audit logger). For application logging, use the Logger interface.
    """
    return structlog.get_logger(name)