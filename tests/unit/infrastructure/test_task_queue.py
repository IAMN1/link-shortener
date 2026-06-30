from unittest.mock import Mock

from link_shortener.application.context import RequestContext
from link_shortener.infrastructure.task_queue.null_queue import NullTaskQueue


class TestNullTaskQueue:
    """Tests for NullTaskQueue synchronous fallback."""

    def test_no_op_when_no_update_fn(self):
        q = NullTaskQueue()
        ctx = RequestContext(request_id="test")
        q.enqueue_link_accessed("abc123", ctx)

    def test_calls_update_fn_synchronously(self):
        fn = Mock()
        q = NullTaskQueue(update_fn=fn)
        ctx = RequestContext(request_id="test")
        q.enqueue_link_accessed("abc123", ctx)
        fn.assert_called_once_with("abc123", ctx)

    def test_swallows_exceptions_from_update_fn(self):
        fn = Mock(side_effect=RuntimeError("db down"))
        q = NullTaskQueue(update_fn=fn)
        ctx = RequestContext(request_id="test")
        q.enqueue_link_accessed("abc123", ctx)

    def test_set_update_fn(self):
        q = NullTaskQueue()
        fn = Mock()
        q.set_update_fn(fn)
        ctx = RequestContext(request_id="test")
        q.enqueue_link_accessed("xyz789", ctx)
        fn.assert_called_once_with("xyz789", ctx)
