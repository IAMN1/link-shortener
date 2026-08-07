from link_shortener.application import TaskQueue
from link_shortener.infrastructure.task_queue.celery_queue import CeleryTaskQueue
from link_shortener.infrastructure.task_queue.null_queue import NullTaskQueue

class TaskQueueComponent:
    """
    Provides a singleton ``TaskQueue`` implementation.

    When Celery is enabled, tasks are sent to a Celery worker; otherwise
    the click counter is updated synchronously via ``UpdateLinkStatsUseCase``.
    """
    def __init__(self, celery_enabled: bool, logger, retry_interval: int = 10):
        """
        Args:
            celery_enabled: If True, use Celery.
            logger: Application logger for diagnostics.
            retry_interval: Seconds the Celery queue stops dispatching for
                after a failed publish. Shares the value with the cache: both
                are backing off from the same Redis.
        """
        self.celery_enabled = celery_enabled
        self.logger = logger
        self.retry_interval = retry_interval
        self._queue = None
        self._update_stats_fn = None

    def set_update_stats_fn(self, fn) -> None:
        """Set the synchronous stats update function for NullTaskQueue."""
        self._update_stats_fn = fn
        # If NullTaskQueue is already created, wire the function now
        if self._queue is not None and isinstance(self._queue, NullTaskQueue):
            self._queue.set_update_fn(fn)

    def get_task_queue(self) -> TaskQueue:
        """
        Return the configured task queue.

        Returns:
            ``CeleryTaskQueue`` or ``NullTaskQueue``.
        """
        if self._queue is None:
            if self.celery_enabled:
                self._queue = CeleryTaskQueue(
                    logger=self.logger, retry_interval=self.retry_interval
                )
            else:
                self.logger.info("Celery disabled, using NullTaskQueue (synchronous fallback)")
                self._queue = NullTaskQueue()
                if self._update_stats_fn:
                    self._queue.set_update_fn(self._update_stats_fn)
        return self._queue
