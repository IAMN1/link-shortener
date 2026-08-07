from typing import Any, Optional

from link_shortener.infrastructure.configs.app.env import env_float, env_str


class BrokerSocketOptions:
    """
    Descriptor building ``broker_transport_options`` at attribute access time.

    A dict literal in the class body cannot be used: building a dict reads
    the lazy fields instead of storing them, so the socket bounds would
    freeze whatever the environment held at import time -- the exact problem
    the descriptors exist to avoid.

    Only the *connect* and *read* bounds are set here. They apply to the
    publishing side, where an unbounded wait blocks an HTTP request; the
    worker drives its blocking pop through the event loop, not through a
    blocking socket read, so it is not cut short by them.

    ``max_retries`` is what actually bounds a dead broker. The socket
    timeouts cap a single attempt, but ``Connection.default_channel`` wraps
    that attempt in ``ensure_connection``, whose back-off (2s, 4s, 6s, 8s)
    accounted for the measured 19.5 seconds per redirect: a refused
    connection returns instantly, and all of the time went into sleeping
    between retries. The worker is unaffected -- it establishes its consumer
    connection with an explicit retry count of its own, taken from
    ``broker_connection_max_retries``.
    """

    def __get__(self, instance: Any, owner: Optional[type] = None) -> dict:
        """
        Args:
            instance: Unused; the options never depend on instance state.
            owner: The configuration class, used to read the timeout field.

        Returns:
            Transport options for the broker connection.
        """
        timeout = owner.broker_connection_timeout

        return {
            "socket_connect_timeout": timeout,
            "socket_timeout": timeout,
            # A timed-out command is a failure to report, not something to
            # sit through a second time.
            "retry_on_timeout": False,
            # One attempt, then report. See the class docstring.
            "max_retries": 0,
        }


class CeleryConfig:
    """
    Celery configuration class.

    This class is passed to Celery's `config_from_object` method.
    All settings are read from environment variables.

    Values use the lazy env descriptors for the same reason as the application
    config: a plain ``os.environ.get()`` in the class body runs at import time,
    before ``.env`` is loaded, so a locally started worker would come up with
    ``broker_url = None`` while the web application considered the broker
    configured.
    """


    # --------------------------------------------------------------------------
    # Broker and Backend URLs
    # --------------------------------------------------------------------------
    broker_url = env_str("CELERY_BROKER_URL")
    """
    URL of the message broker (e.g., redis://:password@redis:6379/0).
    Required for Celery to function.
    """

    result_backend = env_str("CELERY_RESULT_BACKEND")
    """
    URL of the result backend (optional, can be same as broker).
    Stores task results if needed.
    """


    # --------------------------------------------------------------------------
    # Publishing bounds
    # --------------------------------------------------------------------------
    # Enqueuing happens inside an HTTP request, so every wait on the broker is
    # a wait the client sees. Without these bounds a stopped broker cost 19.5
    # seconds per redirect and a broker that accepted TCP without answering
    # never returned at all -- while the response was still a 302 and /health
    # still said the service was fine.
    broker_connection_timeout = env_float("CELERY_BROKER_TIMEOUT", 2.0)
    """
    Seconds to wait for a broker connection before giving up.

    Applies to producers and to the worker alike; the worker simply retries,
    so a short value costs it nothing.
    """

    broker_transport_options = BrokerSocketOptions()
    """Socket-level bounds for the broker connection."""

    task_publish_retry = False
    """
    Do not retry publishing a task.

    Producer-side only. This queue carries click statistics, so a broker
    that is down costs a lost counter increment; retrying instead spends the
    caller's request on a broker that is already known to be unreachable.
    """

    task_ignore_result = True
    """
    Do not store task results.

    Nothing in the application reads one back -- the only task increments a
    click counter. Storing them was not merely wasteful: ``send_task``
    announces every task to the result store before publishing it, and with
    the store unreachable that announcement is what cost the redirect 19.5
    seconds. The broker connection itself failed in 0.14s.
    """

    result_backend_transport_options = {
        # Should results ever be switched back on, the store must not be able
        # to stall a request either: its default policy is 20 retries a
        # second apart, which is where those 19.5 seconds came from.
        "retry_policy": {"max_retries": 0},
    }
    """Bounds for talking to the result store."""


    # --------------------------------------------------------------------------
    # Serialization
    # --------------------------------------------------------------------------
    task_serializer = "json"
    """
    Format for serializing task messages.
    JSON is recommended for cross-language compatibility and security.
    """    

    accept_content = ["json"]
    """
    Allowed content types for incoming task messages.
    """

    result_serializer = "json"
    """
    Format for serializing task results.
    """    


    # --------------------------------------------------------------------------
    # Timezone and UTC
    # --------------------------------------------------------------------------
    timezone = "UTC"
    """
    Timezone used by Celery workers for scheduling and logging.
    """    

    enable_utc = True
    """
    Use UTC internally for all datetime operations.
    """    


    # --------------------------------------------------------------------------
    # Logging
    # --------------------------------------------------------------------------
    worker_hijack_root_logger = False
    """
    Prevent Celery from overriding the root logger configuration.
    Allows our application logging setup to remain in control.
    """
