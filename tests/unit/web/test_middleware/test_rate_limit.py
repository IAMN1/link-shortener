"""Tests for the rate limiting middleware."""
from unittest.mock import MagicMock, Mock

from flask import Flask, g


class TestRateLimitMiddleware:
    """Tests for RateLimitMiddleware."""

    def _make_app(self, rate_limiter=None, rate_limits=None, auth_disabled=False):
        """Create a Flask app with RateLimitMiddleware for testing."""
        from link_shortener.web.middleware.rate_limit import RateLimitMiddleware

        app = Flask(__name__)
        app.config["TESTING"] = True
        app.config["DEFAULT_RATE_LIMIT"] = 5
        app.config["DEFAULT_RATE_LIMIT_PERIOD"] = 60
        app.config["RATE_LIMIT_AUTH_DISABLED"] = auth_disabled
        if rate_limits:
            app.config["RATE_LIMITS"] = rate_limits

        if rate_limiter is None:
            rate_limiter = Mock()
            rate_limiter.is_allowed.return_value = True
            rate_limiter.get_remaining.return_value = 4

        RateLimitMiddleware(app, rate_limiter)

        @app.route("/test")
        def test_view():
            return "ok", 200

        @app.route("/auth/test", endpoint="auth.login")
        def auth_test():
            return "ok", 200

        return app, rate_limiter

    def test_request_allowed(self):
        """Request within rate limit returns 200 with rate limit headers."""
        app, limiter = self._make_app()
        with app.test_client() as client:
            response = client.get("/test")
            assert response.status_code == 200
            assert "X-RateLimit-Limit" in response.headers
            assert "X-RateLimit-Remaining" in response.headers

    def test_request_rate_limited(self):
        """Request exceeding rate limit returns 429."""
        limiter = Mock()
        limiter.is_allowed.return_value = False
        limiter.get_remaining.return_value = 0

        app, _ = self._make_app(rate_limiter=limiter)
        with app.test_client() as client:
            response = client.get("/test")
            assert response.status_code == 429
            data = response.get_json()
            assert data["error"] == "RATE_LIMIT_EXCEEDED"
            assert "X-RateLimit-Limit" in response.headers
            assert "Retry-After" in response.headers

    def test_rate_limit_headers_added(self):
        """Normal response includes rate limit headers."""
        app, limiter = self._make_app()
        with app.test_client() as client:
            response = client.get("/test")
            assert response.headers.get("X-RateLimit-Limit") == "5"
            assert response.headers.get("X-RateLimit-Remaining") == "4"

    def test_custom_rate_limit_per_endpoint(self):
        """Custom per-endpoint rate limits are used when configured."""
        limiter = Mock()
        limiter.is_allowed.return_value = True
        limiter.get_remaining.return_value = 9

        # Use the endpoint name (view function name) as key
        app, _ = self._make_app(
            rate_limiter=limiter,
            rate_limits={"test_view": (10, 120)},
        )
        with app.test_client() as client:
            response = client.get("/test")
            assert response.status_code == 200
            assert response.headers.get("X-RateLimit-Limit") == "10"

    def test_auth_disabled_skips_rate_limit(self):
        """Auth endpoints skip rate limiting when auth_disabled is True."""
        limiter = Mock()
        limiter.is_allowed.return_value = False
        limiter.get_remaining.return_value = 0

        app, _ = self._make_app(rate_limiter=limiter, auth_disabled=True)
        with app.test_client() as client:
            response = client.get("/auth/test")
            # Auth endpoint should skip rate limiting
            assert response.status_code == 200
            limiter.is_allowed.assert_not_called()

    def test_client_id_uses_ip_for_anonymous(self):
        """Anonymous user uses IP as client identifier."""
        limiter = Mock()
        limiter.is_allowed.return_value = True
        limiter.get_remaining.return_value = 4

        app, _ = self._make_app(rate_limiter=limiter)
        with app.test_client() as client:
            response = client.get("/test")
            call_args = limiter.is_allowed.call_args
            key = call_args[0][0]
            # Should not contain "user:" prefix
            assert "user:" not in key

    def test_key_includes_endpoint(self):
        """Rate limit key includes the endpoint name."""
        limiter = Mock()
        limiter.is_allowed.return_value = True
        limiter.get_remaining.return_value = 4

        app, _ = self._make_app(rate_limiter=limiter)
        with app.test_client() as client:
            client.get("/test")
            call_args = limiter.is_allowed.call_args
            key = call_args[0][0]
            assert "test_view" in key
