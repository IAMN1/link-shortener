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

    @abstractmethod
    def enqueue_verification_email(
        self, email: str, token: str, context: RequestContext
    ) -> bool:
        """
        Hand off the confirmation message for an address.

        Unlike ``enqueue_link_accessed``, which may fail in silence
        because a lost click is a lost counter, this one reports. A
        confirmation that never went out leaves somebody unable to finish
        registering, and the only way anyone finds out is if the service
        says so.

        The token travels with the task, in the clear, because only its
        digest is stored and there is nothing else to send. That puts a
        live credential in the broker for as long as the task waits there
        -- the price of doing this in the background rather than on the
        request thread.

        Args:
            email: Address to send to.
            token: The confirmation token as it goes into the link.
            context: Request context with audit metadata.

        Returns:
            True if the message was handed over -- published to the broker,
            or sent outright where there is no broker. False if it was not,
            in which case nothing was sent and nothing will be.
        """
        ...

    @abstractmethod
    def enqueue_account_exists_email(
        self, email: str, context: RequestContext
    ) -> bool:
        """
        Hand off the notice that an address is already registered.

        No token travels with this one, and that is the difference from
        the method above: nothing in this task is a credential. The
        address still travels, and so does the fact that a task of this
        kind was published at all -- which says the address is registered.
        A broker holds less than it does for the other message, not
        nothing.

        Args:
            email: Address to send to.
            context: Request context with audit metadata.

        Returns:
            True if the message was handed over. False if it was not --
            which the caller records but does not report, because a
            registration attempt on a taken address must look the same
            from outside whatever the mail server is doing.
        """
        ...
