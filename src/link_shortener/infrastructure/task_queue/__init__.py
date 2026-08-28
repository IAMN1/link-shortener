"""
Work a request asks for and must not wait on.

What goes in is the dispatch and the task bodies for it: the broker
configuration, the queue that satisfies the port, and the functions a worker
runs. What qualifies is that the request is done either way -- the counter
is incremented, the message is sent, and the caller is answered before any
of it happens.
"""

from .celery_app import celery_app
from .celery_queue import CeleryTaskQueue
from .null_queue import NullTaskQueue

__all__ = [
    'celery_app',
    'CeleryTaskQueue',
    'NullTaskQueue',
]