import os

class CeleryConfig:
    """
    Celery configuration class.

    This class is passed to Celery's `config_from_object` method.
    All settings are read from environment variables.
    """
    

    # --------------------------------------------------------------------------
    # Broker and Backend URLs
    # --------------------------------------------------------------------------
    broker_url = os.environ.get("CELERY_BROKER_URL")
    """
    URL of the message broker (e.g., redis://:password@redis:6379/0).
    Required for Celery to function.
    """    

    result_backend = os.environ.get("CELERY_RESULT_BACKEND")
    """
    URL of the result backend (optional, can be same as broker).
    Stores task results if needed.
    """    


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
