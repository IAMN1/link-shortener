from flask import g, jsonify, request
from link_shortener.application import RateLimiter
from link_shortener.web.security.context import get_client_ip


class RateLimitMiddleware:
    """
    Applies rate limiting to all incoming requests.

    Limits are defined per endpoint; endpoints without specific
    configuration use the default limits. When exceeded, a 429 response
    with standard rate-limit headers is returned.
    """

    def __init__(self, app, rate_limiter: RateLimiter):
        """
        Args:
            app: Flask application instance.
            rate_limiter: Concrete rate limiter implementation.
        """
        self.app = app
        self.rate_limiter = rate_limiter

        # Default limits (can be overridden in Flask config).
        self.default_limit = app.config.get("DEFAULT_RATE_LIMIT", 100)
        self.default_period = app.config.get("DEFAULT_RATE_LIMIT_PERIOD", 60)

        self.rate_limits = app.config.get("RATE_LIMITS", {})
        self.auth_disabled = app.config.get("RATE_LIMIT_AUTH_DISABLED", False)

        self._register_handlers()
    
    def _register_handlers(self):
        """Install ``before_request`` and ``after_request`` hooks."""
        @self.app.before_request
        def check_rate_limit():
            """
            Before each request: build a key, determine the appropriate limit,
            and check with the rate limiter. If limit is exceeded, abort with 429.
            """
            
            # Build client identifier: user ID if authenticated, otherwise IP.
            if hasattr(g, "current_user") and g.current_user:
                client_id = f"user:{g.current_user.id}"
            else:
                client_id = get_client_ip()

            # Combine client ID with endpoint to isolate limits per endpoint.
            key = f"{client_id}:{request.endpoint}"

            # Skip rate limiting for auth endpoints if disabled
            if self.auth_disabled and request.endpoint and request.endpoint.startswith("auth."):
                return

            limit, period = self.rate_limits.get(
                request.endpoint, (self.default_limit, self.default_period)
            )
            
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
            After each request: add (X-RateLimit-*) headers to the response,
            if they were set during the before_request phase.
            """
            if hasattr(g, "rate_limit_limit"):
                response.headers['X-RateLimit-Limit'] = str(g.rate_limit_limit)
                response.headers['X-RateLimit-Remaining'] = str(g.rate_limit_remaining)
            return response
