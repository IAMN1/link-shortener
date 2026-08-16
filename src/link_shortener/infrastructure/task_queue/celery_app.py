from celery import Celery
from celery.signals import setup_logging as celery_is_configuring_logging

from link_shortener.infrastructure.configs.app.factory import get_config
from link_shortener.infrastructure.configs.celery.celery_config import CeleryConfig
from link_shortener.infrastructure.logging.bootstrap import setup_logging
from link_shortener.infrastructure.logging.logging_settings import (
    attribute_reader, logging_settings_from,
)


class LinkShortenerCelery(Celery):
    """
    Celery application that publishes the `.env` files before reading its own
    configuration.

    A worker started as `celery -A ... worker` never goes through
    ``create_app``, so nothing else would load `.env` and the broker URL would
    come out empty even though the web application sees it.

    The work happens in ``on_configure`` – called lazily, the first time the
    configuration is actually needed – rather than at import time. Doing it at
    import would turn `import link_shortener.infrastructure` into a full
    configuration build: every CLI command, test collection and unrelated
    import would then depend on a valid profile being configured.
    """

    def on_configure(self) -> None:
        """Load the application config so `.env` reaches ``os.environ``."""
        get_config()


@celery_is_configuring_logging.connect
def configure_logging(**_kwargs) -> None:
    """
    Give the worker the journals the application writes.

    A worker never goes through ``create_app``, which is the only other
    caller of ``setup_logging`` -- so with `LOG_TO_FILE=true` the web
    processes wrote three files and the worker wrote none of them. What a
    task logged, including the failure of one, existed only in the
    container's standard output: not in ``error.log``, not in the journals
    an incident is reconstructed from, and not in whatever ends up
    displaying them.

    Connecting to this signal at all is what stops Celery configuring
    logging its own way; that is the documented meaning of having a
    receiver on it, and it is why this does not fight the worker for the
    root logger.

    Failed writes do not raise here, which is the one difference from the
    web process. Raising exists to feed ``FailoverService``, which catches
    it and moves the work to another logger. A worker has no such service
    behind its module loggers, so a raised write would not be handled by
    anything -- it would simply turn a lost log line into a failed task.

    Several processes now write the same three files: four gunicorn
    workers, this worker, and its prefork children. That is what the
    rotation is built for -- see ``docs/decisions.md``, "Rotation is
    somebody else's job" -- and it is the reason nothing here rotates
    anything.

    Args:
        **_kwargs: Celery's signal arguments, none of which are used.
    """
    config = get_config()
    settings = logging_settings_from(
        attribute_reader(config), raise_on_write_failure=False
    )
    setup_logging(
        settings,
        logging_enabled=getattr(config, "LOGGING_ENABLED", True),
        audit_enabled=getattr(config, "AUDIT_ENABLED", True),
    )


# Create the Celery application instance.
celery_app = LinkShortenerCelery("link_shortener")

# Load configuration from the CeleryConfig class.
celery_app.config_from_object(CeleryConfig)

# Automatically discover tasks in the `infrastructure.task_queue` module.
celery_app.autodiscover_tasks(["link_shortener.infrastructure.task_queue"])
