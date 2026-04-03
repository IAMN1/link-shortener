from link_shortener.application.context import RequestContext
from link_shortener.application.ports.task_queue import TaskQueue


class NullTaskQueue(TaskQueue):
    """
    Null-object implementation of `TaskQueue`.

    All methods do nothing. Used when Celery is disabled
    (CELERY_ENABLED=False) or as a fallback.
    """

    def enqueue_link_accessed(self, short_code_str: str, context: RequestContext) -> None:
        """No-op: do nothing."""
        pass
