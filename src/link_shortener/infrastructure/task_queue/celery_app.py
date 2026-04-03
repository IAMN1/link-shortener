from celery import Celery

from link_shortener.infrastructure.configs.celery.celery_config import CeleryConfig

# Create the Celery application instance.
celery_app = Celery("link_shortener")

# Load configuration from the CeleryConfig class.
celery_app.config_from_object(CeleryConfig)

# Automatically discover tasks in the `infrastructure.task_queue` module.
celery_app.autodiscover_tasks(["link_shortener.infrastructure.task_queue"])
