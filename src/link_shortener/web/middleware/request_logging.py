import time
import uuid

from flask import Flask, Response, g, request

from link_shortener.application import Logger
from link_shortener.web.middleware.hooks import response_hook


class RequestLoggingMiddleware:
    """
    Logs incoming requests and their outcomes.

    Sets ``g.start_time`` and ``g.request_id`` early in the request
    lifecycle, then logs request and response metadata.
    """

    def __init__(self, app: Flask, logger: Logger):
        """
        Args:
            app: Flask application instance.
            logger: Logger for request logs.
        """

        self.app = app
        self.logger = logger
        self._register_handlers()

    def _register_handlers(self):
        """Register before_request and after_request hooks."""

        @self.app.before_request
        def before_request():
            """
            Executed before each request.

            Sets start time and generates a request ID, stored in Flask's `g` object.
            Logs the start of the request.
            """
            # Skip logging for static file requests.
            if request.path.startswith('/static/'):
                return

            g.start_time = time.time()
            g.request_id = str(uuid.uuid4())[:10]

            user_agent = request.headers.get('User-Agent')

            self.logger.info(
                "Request started",
                method=request.method,
                path=request.path,
                remote_addr=request.remote_addr,
                request_id=g.request_id,
                user_agent=user_agent
            )

        @self.app.after_request
        @response_hook(self.logger)
        def after_request(response: Response):
            """
            Executed after each request (before sending response).
            Calculates request duration and logs completion.
            """
            # Skip if the request was for a static file.
            if request.path.startswith('/static/'):
                return response

            if hasattr(g, 'start_time'):

                duration = time.time() - g.start_time

                self.logger.info(
                    "Request completed",
                    status=response.status_code,
                    duration_ms=round(duration * 1000, 2),
                    request_id=getattr(g, "request_id", None)
                )
            return response
