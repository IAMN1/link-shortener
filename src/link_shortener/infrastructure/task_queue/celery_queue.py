import time
from threading import Lock

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.task_queue import TaskQueue


class CeleryTaskQueue(TaskQueue):
    """
    Sends tasks to a Celery worker.

    The ``RequestContext`` is serialised into a dictionary and passed as a
    task argument. Three tasks are dispatched from here:
    ``process_link_accessed``, ``send_verification_email`` and
    ``send_account_exists_email``.

    Dispatching happens on the request path, so an unreachable broker is a
    latency problem before it is a correctness one. Two things bound it: the
    socket timeouts in ``CeleryConfig``, which cap a single attempt, and the
    back-off below, which stops the service from paying that cap again on
    every request while the broker stays down.

    Attributes:
        celery_app: The Celery application, exposed so that the health check
            can ask the broker whether any worker is listening. Without a
            worker the enqueued tasks are simply never run, and nothing else
            in the system would notice.
        logger: Application logger, used when a task cannot be dispatched.
        retry_interval: Seconds to skip dispatching after a failure.
    """

    def __init__(self, logger: Logger = None, retry_interval: int = 10):
        """
        Args:
            logger: Application logger for diagnostics.
            retry_interval: Seconds to stop dispatching for after a failed
                publish, before probing the broker again.
        """
        from link_shortener.infrastructure.task_queue.celery_app import celery_app

        self.celery_app = celery_app
        self.logger = logger
        self.retry_interval = retry_interval

        self._lock = Lock()
        self._failed_at: float | None = None

    def _claim_attempt(self) -> bool:
        """
        Decide, once per interval, which caller retries the broker.

        Two things this must not do. It must not let every caller through
        at once: each one pays the full broker timeout, so a burst of
        traffic during an outage degrades every request instead of one.
        And it must not clear the failure merely because it was asked --
        the winner stamps the clock *before* attempting, so losers see a
        closed window and return immediately.

        Returns:
            True if this caller should attempt to publish.
        """
        with self._lock:
            if self._failed_at is None:
                return True

            if time.monotonic() - self._failed_at < self.retry_interval:
                return False

            # Claim the retry: let this caller find out whether the broker
            # came back, and hold everyone else off meanwhile.
            self._failed_at = time.monotonic()
            return True

    def enqueue_link_accessed(self, short_code_str: str, context: RequestContext) -> None:
        """
        Enqueue a Celery task to update link click statistics.

        A broker that cannot be reached must not take the request down with
        it. This queue only carries click statistics, so failing to dispatch
        costs a lost counter increment -- letting the error escape instead
        turned every redirect into a 500 for as long as the broker was
        unreachable, and waiting on it turned every redirect into a timeout.

        Args:
            short_code_str: The short code of the accessed link.
            context: ``RequestContext`` containing request metadata.
        """

        if not self._claim_attempt():
            return

        # Serialize RequestContext to a plain dictionary.
        from link_shortener.infrastructure.task_queue.tasks import process_link_accessed
        context_dict = {
            'request_id': context.request_id,
            'remote_addr': context.remote_addr,
            'user_agent': context.user_agent,
            'request_path': context.request_path,
            'request_method': context.request_method,
        }
        # Dispatch the task asynchronously.
        try:
            process_link_accessed.delay(short_code_str, context_dict)
            with self._lock:
                self._failed_at = None
        except Exception as e:
            with self._lock:
                self._failed_at = time.monotonic()
            if self.logger:
                self.logger.error(
                    "Failed to enqueue link access task, click not counted",
                    error=str(e),
                    short_code=short_code_str,
                    suspended_for=self.retry_interval,
                )

    def enqueue_verification_email(
        self, email: str, token: str, context: RequestContext
    ) -> bool:
        """
        Publish the confirmation message as a task for a worker.

        The back-off above is deliberately not consulted here. It exists
        so that a burst of redirects does not each pay the broker timeout
        during an outage, and it is right for a counter -- but it decides
        by the clock, not by the request, and a registration skipped
        because some redirect failed a moment ago would leave a person
        with no way to confirm and no way to know why. Registration is
        rare enough to be worth one attempt each time.

        Args:
            email: Address to send to.
            token: The confirmation token as it goes into the link.
            context: ``RequestContext`` containing request metadata.

        Returns:
            True if the task was published.
        """
        from link_shortener.infrastructure.task_queue.tasks import (
            send_verification_email,
        )

        context_dict = {
            'request_id': context.request_id,
            'remote_addr': context.remote_addr,
            'user_agent': context.user_agent,
            'request_path': context.request_path,
            'request_method': context.request_method,
        }
        try:
            send_verification_email.delay(email, token, context_dict)
            return True
        except Exception as e:
            if self.logger:
                # The token is not logged. It is a working credential for
                # as long as it lives, and a log outlives a mailbox.
                self.logger.error(
                    "Failed to enqueue verification email",
                    error=str(e),
                    email=email,
                )
            return False

    def enqueue_account_exists_email(
        self, email: str, context: RequestContext
    ) -> bool:
        """
        Publish the "already registered" notice as a task for a worker.

        The back-off is not consulted here either, and for the reason
        above: this message belongs to one registration attempt, not to a
        stream of them.

        Args:
            email: Address to send to.
            context: ``RequestContext`` containing request metadata.

        Returns:
            True if the task was published.
        """
        from link_shortener.infrastructure.task_queue.tasks import (
            send_account_exists_email,
        )

        context_dict = {
            'request_id': context.request_id,
            'remote_addr': context.remote_addr,
            'user_agent': context.user_agent,
            'request_path': context.request_path,
            'request_method': context.request_method,
        }
        try:
            send_account_exists_email.delay(email, context_dict)
            return True
        except Exception as e:
            if self.logger:
                self.logger.error(
                    "Failed to enqueue account-exists notice",
                    error=str(e),
                    email=email,
                )
            return False
