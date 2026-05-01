from link_shortener.application import TaskQueue
from link_shortener.infrastructure.task_queue.celery_queue import CeleryTaskQueue
from link_shortener.infrastructure.task_queue.null_queue import NullTaskQueue

class TaskQueueComponent:
    """
    Provides a singleton ``TaskQueue`` implementation.

    When Celery is enabled, tasks are sent to a Celery worker; otherwise
    they are silently discarded (``NullTaskQueue``).
    """
    def __init__(self, celery_enabled: bool, logger):
        """
        Args:
            celery_enabled: If True, use Celery.
            logger: Application logger for diagnostics.
        """
        self.celery_enabled = celery_enabled
        self.logger = logger
        self._queue = None

    def get_task_queue(self) -> TaskQueue:
        """
        Return the configured task queue.

        Returns:
            ``CeleryTaskQueue`` or ``NullTaskQueue``.
        """
        if self._queue is None:
            if self.celery_enabled:
                self._queue = CeleryTaskQueue()
            else:
                self.logger.info("Celery disabled, using NullTaskQueue")
                self._queue = NullTaskQueue()
        return self._queue
