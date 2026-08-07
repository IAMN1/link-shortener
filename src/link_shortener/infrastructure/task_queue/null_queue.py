from typing import Callable, Optional

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.task_queue import TaskQueue


class NullTaskQueue(TaskQueue):
    """
    Null-object implementation of `TaskQueue`.

    When Celery is disabled, executes the stat update synchronously
    via a provided callback. Falls back to no-op if no callback is set.
    """

    def __init__(self, update_fn: Optional[Callable] = None):
        self._update_fn = update_fn

    def set_update_fn(self, update_fn: Callable) -> None:
        """Set the synchronous update function (called when Celery is off)."""
        self._update_fn = update_fn

    def enqueue_link_accessed(self, short_code_str: str, context: RequestContext) -> None:
        if self._update_fn:
            try:
                self._update_fn(short_code_str, context)
            except Exception:
                pass  # Best-effort: don't crash the redirect
