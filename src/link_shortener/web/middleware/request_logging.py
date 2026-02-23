import time
import uuid

from flask import Flask, Response, g, request

from link_shortener.application import Logger


class RequestLoggingMiddleware:
    """
    Middleware for logging HTTP requests and responses.

    Adds a unique request ID, logs request start, and logs completion with duration.
    """
    
    def __init__(self, app: Flask, logger: Logger):
        """
        Initialize the middleware and register 
            before/after request handlers.

        Args:
            app (Flask): Flask application instance
            logger (Logger): Logger instance for request logging.
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

            g.start_time = time.time()
            g.request_id = str(uuid.uuid4())[:10]

            self.logger.info(
                "Request started", 
                method=request.method,
                path=request.path, 
                remote_addr=request.remote_addr,
                request_id=g.request_id,
                user_agent=request.user_agent.string if request.user_agent else None
            )

        @self.app.after_request
        def after_request(response: Response):
            """
            Executed after each request (before sending response).
            Calculates request duration and logs completion.
            """
            if hasattr(g, 'start_time'):
                
                duration = time.time() - g.start_time
                
                self.logger.info(
                    "Request completed",
                    status=response.status_code,
                    duration_ms=round(duration * 1000, 2),
                    request_id=getattr(g, "request_id", None)
                )
            return response
