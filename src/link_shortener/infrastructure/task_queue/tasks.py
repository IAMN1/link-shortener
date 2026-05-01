import functools
import structlog
from link_shortener.application.context import RequestContext
from link_shortener.infrastructure.configs.app.factory import get_config
from link_shortener.infrastructure.task_queue import celery_app
from link_shortener.infrastructure.di.container import Container

logger = structlog.getLogger(__name__)

@functools.lru_cache(maxsize=1)
def get_container():
    """
    Create and cache the dependency injection container for the current worker process.

    This function is called once per worker process (because of the `lru_cache`
    decorator that will be added later). It reads the configuration and
    builds a `Container` instance.

    Returns:
        Container: The DI container instance.

    Raises:
        Exception: If container creation fails (logged but returns None).
    """
    config = get_config()
    try:
        cont = Container(config)
        return cont
    except Exception:
        return None

@celery_app.task(bind=True, max_retries=3)
def process_link_accessed(self, short_code: str, context_dict: dict):
    """
    Celery task to asynchronously update link statistics (click count).

    This task is triggered by `CeleryTaskQueue.enqueue_link_accessed`.
    It reconstructs the `RequestContext` from the dictionary, obtains the
    DI container, and executes `UpdateLinkStatsUseCase`.

    Args:
        short_code: The short code of the accessed link.
        context_dict: Serialized `RequestContext` fields.

    Raises:
        Exception: On failure, the task is retried up to 3 times with a 60s delay.
    """
    try:
        context = RequestContext(**context_dict)
        container = get_container()
        if container is None:
            raise RuntimeError("Container is None")
        use_case = container.get_update_link_stats_use_case()
        use_case.execute(short_code, context)
        logger.info("Stats updated", short_code=short_code)
    except Exception as exc:
        logger.exception("Error processing link accessed task", exc_info=exc)
        self.retry(exc=exc, countdown=60)
