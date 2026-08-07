from abc import ABC, abstractmethod

from link_shortener.application.context import RequestContext


class TaskQueue(ABC):
    """
    Abstract interface for an asynchronous task queue.

    Used to offload non-critical operations (e.g., updating click counts)
    to background workers.
    """

    @abstractmethod
    def enqueue_link_accessed(self, short_code: str, context: RequestContext) -> None:
        """
        Enqueue a background task to update link access statistics.

        Args:
            short_code: The short code of the accessed link.
            context: Request context with audit metadata.
        """
        ...
