from celery import Celery

from link_shortener.infrastructure.configs.app.factory import get_config
from link_shortener.infrastructure.configs.celery.celery_config import CeleryConfig


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


# Create the Celery application instance.
celery_app = LinkShortenerCelery("link_shortener")

# Load configuration from the CeleryConfig class.
celery_app.config_from_object(CeleryConfig)

# Automatically discover tasks in the `infrastructure.task_queue` module.
celery_app.autodiscover_tasks(["link_shortener.infrastructure.task_queue"])
