from typing import Callable, Optional
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
        # Annotated Optional rather than inferred from these assignments:
        # each holds None until the first call builds it.
        self._queue: Optional[TaskQueue] = None
        self._update_stats_fn: Optional[Callable[..., None]] = None
        self._send_verification_fn: Optional[Callable[..., None]] = None
        self._send_account_exists_fn: Optional[Callable[..., None]] = None

    def set_update_stats_fn(self, fn) -> None:
        """Set the synchronous stats update function for NullTaskQueue."""
        self._update_stats_fn = fn
        # If NullTaskQueue is already created, wire the function now
        if self._queue is not None and isinstance(self._queue, NullTaskQueue):
            self._queue.set_update_fn(fn)

    def set_send_verification_fn(self, fn) -> None:
        """Set the synchronous mail function for NullTaskQueue.

        Args:
            fn: Callable with signature ``(email, token, context)``.
        """
        self._send_verification_fn = fn
        if self._queue is not None and isinstance(self._queue, NullTaskQueue):
            self._queue.set_send_verification_fn(fn)

    def set_send_account_exists_fn(self, fn) -> None:
        """Set the synchronous notice function for NullTaskQueue.

        Args:
            fn: Callable with signature ``(email, context)``.
        """
        self._send_account_exists_fn = fn
        if self._queue is not None and isinstance(self._queue, NullTaskQueue):
            self._queue.set_send_account_exists_fn(fn)

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
                self._queue = NullTaskQueue(logger=self.logger)
                if self._update_stats_fn:
                    self._queue.set_update_fn(self._update_stats_fn)
                if self._send_verification_fn:
                    self._queue.set_send_verification_fn(self._send_verification_fn)
                if self._send_account_exists_fn:
                    self._queue.set_send_account_exists_fn(
                        self._send_account_exists_fn
                    )
        return self._queue
