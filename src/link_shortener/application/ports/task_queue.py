from abc import ABC, abstractmethod

from link_shortener.application.context import RequestContext


class TaskQueue(ABC):
    """
    Abstract interface for an asynchronous task queue.

    Implementations (e.g., Celery, RQ, in-memory) are responsible for
    offloading long-running or non-critical operations to background workers.
    """

    @abstractmethod
    def enqueue_link_accessed(self, short_code: str, context: RequestContext) -> None:
        """
        Enqueue a task to asynchronously update link statistics (click count).

        The task should retrieve the link by short_code, increment its click
        counter, update the last accessed timestamp, and refresh any caches.

        Args:
            short_code: The short code of the accessed link.
            context: Request context containing metadata (IP, user agent, etc.)
                to be passed to the background worker for audit purposes.
        """
        pass