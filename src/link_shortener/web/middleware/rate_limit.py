from flask import g, jsonify, request
from link_shortener.application import RateLimiter


class RateLimitMiddleware:
    """Flask middleware that applies rate limiting to incoming requests.

    It extracts the client identifier (IP address or user ID) and the
    endpoint name to build a unique key. For each request it checks
    the configured limit for that endpoint and, if exceeded, returns a
    429 response with standard rate-limit headers.

    Limits are defined per endpoint; a fallback default limit is used
    for any unconfigured endpoint."""

    def __init__(self, app, rate_limiter: RateLimiter):
        """
        Initialize the middleware and register before/after request handlers.

        Args:
            app: Flask application instance.
            rate_limiter: Concrete implementation of the rate limiter.
        """
        self.app = app
        self.rate_limiter = rate_limiter

        # Default limits (can be overridden in Flask config)
        self.default_limit = getattr(app.config, "DEFAULT_RATE_LIMIT", 100)
        self.default_period = getattr(app.config, "DEFAULT_RATE_LIMIT_PERIOD", 60)

        self._register_handlers()
    
    def _register_handlers(self):
        """Register Flask's before_request and after_request hooks."""
        @self.app.before_request
        def check_rate_limit():
            """
            Before each request: build a key, determine the appropriate limit,
            and check with the rate limiter. If limit is exceeded, abort with 429.
            """
            # Use client IP (or X-Forwarded-For if behind a proxy) as the identifier.
            client_id = request.headers.get('X-Forwarded-For', request.remote_addr)

            # Combine client ID with endpoint to isolate limits per endpoint.
            key = f"{client_id}:{request.endpoint}"

            # Configure limits per endpoint (hard‑coded for simplicity).
            if request.endpoint == 'api.create_short_link':
                limit = 30
                period = 60
            elif request.endpoint == 'api.get_link_info':
                limit = 100
                period = 60
            elif request.endpoint == 'api.get_extend_link_info':
                limit = 50
                period = 60
            elif request.endpoint == 'api.batch_create':
                limit = 5
                period = 60
            elif request.endpoint == 'api.get_stats':
                limit = 10
                period = 60
            elif request.endpoint == 'redirect_to_original':
                limit == 200
                period = 60
            elif request.endpoint == 'health':
                limit = 10
                period = 5
            else:
                # Fallback to default limits for any other endpoint.
                limit = self.default_limit
                period = self.default_period
            
            if not self.rate_limiter.is_allowed(key, limit, period):
                remaining = self.rate_limiter.get_remaining(key, limit, period)
                response = jsonify({
                    "error": "RATE_LIMIT_EXCEEDED",
                    "message": f"Too many requests. Limit {limit} per {period} seconds.",
                    "retry_after": period
                })
                response.status_code = 429
                response.headers['X-RateLimit-Limit'] = str(limit)
                response.headers['X-RateLimit-Remaining'] = str(remaining)
                response.headers['Retry-After'] = str(period)
                return response
            
            # Store the limit values in the Flask global object so they can be
            # added to the response headers later.
            g.rate_limit_limit = limit
            g.rate_limit_remaining = self.rate_limiter.get_remaining(key, limit, period)
        
        @self.app.after_request
        def add_rate_limit_headers(response):
            """
            After each request: add X‑RateLimit‑* headers to the response,
            if they were set during the before_request phase.
            """
            if hasattr(g, "rate_limit_limit"):
                response.headers['X-RateLimit-Limit'] = str(g.rate_limit_limit)
                response.headers['X-RateLimit-Remaining'] = str(g.rate_limit_remaining)
            return response
