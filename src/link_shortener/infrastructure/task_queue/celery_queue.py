from link_shortener.application.context import RequestContext
from link_shortener.application.ports.task_queue import TaskQueue


class CeleryTaskQueue(TaskQueue):
    """
    Sends tasks to a Celery worker.

    The ``RequestContext`` is serialised into a dictionary and passed as a
    task argument. The actual task function is ``process_link_accessed``.
    """
    def enqueue_link_accessed(self, short_code_str: str, context: RequestContext) -> None:
        """
        Enqueue a Celery task to update link click statistics.

        Args:
            short_code_str: The short code of the accessed link.
            context: ``RequestContext`` containing request metadata.
        """
        
        # Сериализуем RequestContext в словарь
        from link_shortener.infrastructure.task_queue.tasks import process_link_accessed
        context_dict = {
            'request_id': context.request_id,
            'remote_addr': context.remote_addr,
            'user_agent': context.user_agent,
            'request_path': context.request_path,
            'request_method': context.request_method,
        }
        # Отправляем задачу асинхронно
        process_link_accessed.delay(short_code_str, context_dict)
