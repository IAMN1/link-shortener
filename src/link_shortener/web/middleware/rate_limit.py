from flask import g, jsonify, request
from link_shortener.application import RateLimiter
from link_shortener.web.security.context import get_client_ip
from link_shortener.web.middleware.hooks import response_hook
from link_shortener.infrastructure.logging.handlers.logger.null_logger import (
    NullLogger,
)


EXEMPT_ENDPOINTS = frozenset({"health"})
"""Endpoints that must answer regardless of how often they are asked."""


class RateLimitMiddleware:
    """
    Applies rate limiting to all incoming requests.

    Limits are defined per endpoint; endpoints without specific
    configuration use the default limits. When exceeded, a 429 response
    with standard rate-limit headers is returned.
    """

    def __init__(self, app, rate_limiter: RateLimiter, logger=None):
        """
        Args:
            app: Flask application instance.
            rate_limiter: Concrete rate limiter implementation.
            logger: Application logger. Only the response hook uses it, to
                report a failure that must not reach the client.
        """
        self.app = app
        self.rate_limiter = rate_limiter
        self.logger = logger or NullLogger()

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
            
            # Static assets and the health probe are never throttled. The
            # probe is how the orchestrator learns whether this instance is
            # alive, and a 429 is indistinguishable from a real failure to
            # it -- throttling it means a busy service gets restarted.
            if request.path.startswith("/static/") or request.endpoint in EXEMPT_ENDPOINTS:
                return

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
            
            # One call, not two. Asking for the verdict and then for the
            # remaining quota meant a second round trip on every allowed
            # request just to fill in a header -- and against a Redis that
            # had stopped answering, a second full socket timeout.
            decision = self.rate_limiter.check(key, limit, period)

            if not decision.allowed:
                remaining = decision.remaining
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
            g.rate_limit_remaining = decision.remaining
        
        @self.app.after_request
        @response_hook(self.logger)
        def add_rate_limit_headers(response):
            """
            After each request: add (X-RateLimit-*) headers to the response,
            if they were set during the before_request phase.
            """
            if response.status_code == 429:
                # Somebody else refused this request -- the guest quota, in
                # practice, since the throttle's own 429 is built above and
                # returned before this. Stamping the throttle's counters on
                # it produced an answer that contradicted itself: a body
                # saying the daily limit of ten was spent, next to a header
                # saying nineteen requests remained.
                return response

            if hasattr(g, "rate_limit_limit"):
                response.headers['X-RateLimit-Limit'] = str(g.rate_limit_limit)
                response.headers['X-RateLimit-Remaining'] = str(g.rate_limit_remaining)
            return response
