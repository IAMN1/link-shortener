import os

class CeleryConfig:
    """
    Celery configuration class.

    Reads settings from environment variables. This class is passed to
    Celery's `config_from_object` method to configure the Celery app.
    """
    
    # Redis URL used as the message broker (e.g., redis://redis:6379/0).
    broker_url = os.environ.get("CELERY_BROKER_URL")
    
    # Redis URL used as the result backend.
    result_backend = os.environ.get("CELERY_RESULT_BACKEND")
    
    # Serialization format for tasks (JSON is cross‑language safe).
    task_serializer = "json"
    
    # Allowed content types for task messages.
    accept_content = ["json"]
    
    # Serialization format for task results.
    result_serializer = "json"
    
    # Timezone for Celery workers.
    timezone = "UTC"
    
    # Use UTC for all date‑time handling.
    enable_utc = True
    
    # Prevent Celery from overriding the root logger configuration.
    worker_hijack_root_logger = False
