from typing import Callable, Optional

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.task_queue import TaskQueue


class NullTaskQueue(TaskQueue):
    """
    Null-object implementation of `TaskQueue`.

    When Celery is disabled, executes the stat update synchronously
    via a provided callback. Falls back to no-op if no callback is set.

    Confirmation mail is handled the same way, and the difference between
    the two is the point: a lost click is a counter nobody misses, while a
    confirmation that was not sent is somebody who cannot finish
    registering. So the click update swallows whatever it hits, and the
    mail reports whether it went.
    """

    def __init__(
        self,
        update_fn: Optional[Callable] = None,
        send_verification_fn: Optional[Callable] = None,
        send_account_exists_fn: Optional[Callable] = None,
        logger: Optional[Logger] = None,
    ):
        """
        Args:
            update_fn: Synchronous stand-in for the click statistics task.
            send_verification_fn: Synchronous stand-in for the mail task.
            send_account_exists_fn: Synchronous stand-in for the notice
                that an address is already registered.
            logger: Application logger for diagnostics.
        """
        self._update_fn = update_fn
        self._send_verification_fn = send_verification_fn
        self._send_account_exists_fn = send_account_exists_fn
        self.logger = logger

    def set_update_fn(self, update_fn: Callable) -> None:
        """Set the synchronous update function (called when Celery is off)."""
        self._update_fn = update_fn

    def set_send_verification_fn(self, send_fn: Callable) -> None:
        """Set the synchronous mail function (called when Celery is off)."""
        self._send_verification_fn = send_fn

    def set_send_account_exists_fn(self, send_fn: Callable) -> None:
        """Set the synchronous notice function (called when Celery is off)."""
        self._send_account_exists_fn = send_fn

    def enqueue_link_accessed(self, short_code_str: str, context: RequestContext) -> None:
        if self._update_fn:
            try:
                self._update_fn(short_code_str, context)
            except Exception:
                # Best-effort: counting a click must not fail the redirect.
                pass  # nosec B110

    def enqueue_verification_email(
        self, email: str, token: str, context: RequestContext
    ) -> bool:
        """
        Send the confirmation message on the caller's thread.

        Args:
            email: Address to send to.
            token: The confirmation token.
            context: Request context.

        Returns:
            True if the message was sent.
        """
        if not self._send_verification_fn:
            return False

        try:
            self._send_verification_fn(email, token, context)
            return True
        except Exception as e:
            # Registration is not undone by this: the account exists and
            # the token is stored, so the person can ask for the message
            # again. What must not happen is the failure passing unsaid.
            if self.logger:
                self.logger.error(
                    "Verification email not sent", error=str(e), email=email
                )
            return False

    def enqueue_account_exists_email(
        self, email: str, context: RequestContext
    ) -> bool:
        """
        Send the "already registered" notice on the caller's thread.

        Args:
            email: Address to send to.
            context: Request context.

        Returns:
            True if the message was sent.
        """
        if not self._send_account_exists_fn:
            return False

        try:
            self._send_account_exists_fn(email, context)
            return True
        except Exception as e:
            if self.logger:
                self.logger.error(
                    "Account-exists notice not sent", error=str(e), email=email
                )
            return False
