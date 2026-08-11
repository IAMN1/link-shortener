import functools
import structlog
from link_shortener.application.context import RequestContext
from link_shortener.infrastructure.configs.app.factory import get_config
from link_shortener.infrastructure.task_queue import celery_app
from link_shortener.infrastructure.di.container import Container

logger = structlog.getLogger(__name__)

@functools.lru_cache(maxsize=1)
def get_container():
    """
    Create and cache the dependency injection container for the current worker process.

    Returns:
        Container: The DI container instance.

    Raises:
        RuntimeError: If container creation fails.
    """
    config = get_config()
    return Container(config)

@celery_app.task(bind=True, max_retries=3)
def send_verification_email(self, email: str, token: str, context_dict: dict):
    """
    Celery task to send one address confirmation message.

    This task is triggered by ``CeleryTaskQueue.enqueue_verification_email``.

    Retried like the statistics task, and for a better reason: a
    submission server that is briefly unreachable is the ordinary case,
    and the person waiting has no other way to get the message. Retries
    are bounded, so a permanently rejected address stops rather than
    hammering the server.

    Args:
        email: Address to send to.
        token: The confirmation token as it goes into the link.
        context_dict: Serialized ``RequestContext`` fields.

    Raises:
        Exception: On failure, the task is retried up to 3 times with a
            60s delay. Neither the token nor the message body is logged.
    """
    try:
        context = RequestContext(**context_dict)
        container = get_container()
        use_case = container.get_send_verification_email_use_case()
        use_case.execute(email, token, context)
        logger.info("Verification email sent", email=email)
    except Exception as exc:
        logger.error(
            "Error sending verification email", email=email, error=str(exc)
        )
        self.retry(exc=exc, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def send_account_exists_email(self, email: str, context_dict: dict):
    """
    Celery task to tell an address that somebody tried to register it.

    This task is triggered by ``CeleryTaskQueue.enqueue_account_exists_email``.

    Retried like the confirmation message: the address belongs to someone
    who ought to hear that an attempt was made, and a submission server
    that is briefly unreachable should not be the end of it.

    Args:
        email: Address to send to.
        context_dict: Serialized ``RequestContext`` fields.

    Raises:
        Exception: On failure, the task is retried up to 3 times with a
            60s delay.
    """
    try:
        context = RequestContext(**context_dict)
        container = get_container()
        use_case = container.get_send_account_exists_email_use_case()
        use_case.execute(email, context)
        logger.info("Account-exists notice sent", email=email)
    except Exception as exc:
        logger.error(
            "Error sending account-exists notice", email=email, error=str(exc)
        )
        self.retry(exc=exc, countdown=60)


@celery_app.task(bind=True, max_retries=3)
def process_link_accessed(self, short_code: str, context_dict: dict):
    """
    Celery task to asynchronously update link statistics (click count).

    This task is triggered by `CeleryTaskQueue.enqueue_link_accessed`.
    It reconstructs the `RequestContext` from the dictionary, obtains the
    DI container, and executes `UpdateLinkStatsUseCase`.

    Args:
        short_code: The short code of the accessed link.
        context_dict: Serialized `RequestContext` fields.

    Raises:
        Exception: On failure, the task is retried up to 3 times with a 60s delay.
    """
    try:
        context = RequestContext(**context_dict)
        container = get_container()
        use_case = container.get_update_link_stats_use_case()
        use_case.execute(short_code, context)
        logger.info("Stats updated", short_code=short_code)
    except Exception as exc:
        logger.exception("Error processing link accessed task", exc_info=exc)
        self.retry(exc=exc, countdown=60)
