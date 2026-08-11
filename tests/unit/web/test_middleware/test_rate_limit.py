"""Tests for the rate limiting middleware."""
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest
from flask import Flask, g

from link_shortener.application.ports.rate_limiter import RateLimitDecision
from link_shortener.infrastructure.configs.app.base import BaseConfig
from link_shortener.web.middleware.rate_limit import (
    EXEMPT_ENDPOINTS,
    check_rate_limit_targets,
)


def _limiter(allowed=True, remaining=4):
    """
    Build a rate limiter stub.

    The middleware asks for the verdict and the remaining quota in one call,
    so that an allowed request does not pay a second round trip -- or, on a
    Redis that stopped answering, a second socket timeout.

    Args:
        allowed: Whether the request is within the quota.
        remaining: Requests left in the window.

    Returns:
        A mock rate limiter.
    """
    limiter = Mock()
    limiter.check.return_value = RateLimitDecision(
        allowed=allowed, remaining=remaining
    )
    return limiter


TEMPLATES = Path(__file__).resolve().parent / "_stub_templates"
"""A one-line ``error.html``, for the page the throttle now renders.

Not the real template: that one extends the site layout, which links to
half a dozen endpoints this app does not have, so rendering it here would
measure ``url_for`` rather than the limit. What matters at this level is
that the answer is a page and not an envelope; that the real template
renders is the integration tests' business.
"""


class TestRateLimitMiddleware:
    """Tests for RateLimitMiddleware."""

    def _make_app(self, rate_limiter=None, rate_limits=None, auth_disabled=False):
        """Create a Flask app with RateLimitMiddleware for testing.

        The real template folder is handed over because the throttle now
        answers a page on non-API routes, exactly as every other refusal
        there does. Without it these tests would measure a
        ``TemplateNotFound`` instead of a limit.
        """
        from link_shortener.web.middleware.rate_limit import RateLimitMiddleware

        app = Flask(__name__, template_folder=str(TEMPLATES))
        app.config["TESTING"] = True
        app.config["DEFAULT_RATE_LIMIT"] = 5
        app.config["DEFAULT_RATE_LIMIT_PERIOD"] = 60
        app.config["RATE_LIMIT_AUTH_DISABLED"] = auth_disabled
        if rate_limits:
            app.config["RATE_LIMITS"] = rate_limits

        if rate_limiter is None:
            rate_limiter = _limiter()

        RateLimitMiddleware(app, rate_limiter)

        @app.route("/test")
        def test_view():
            return "ok", 200

        @app.route("/auth/test", endpoint="auth.login")
        def auth_test():
            return "ok", 200

        # An API path as well: the throttle answers a page on browser
        # routes and an envelope under /api/, following the same rule the
        # error handler uses, so both have to be reachable from here.
        @app.route("/api/v1/test", endpoint="api.test")
        def api_test():
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
        limiter = _limiter(allowed=False, remaining=0)

        app, _ = self._make_app(rate_limiter=limiter)
        with app.test_client() as client:
            response = client.get("/api/v1/test")
            assert response.status_code == 429
            data = response.get_json()
            assert data["error"] == "RATE_LIMIT_EXCEEDED"
            assert "X-RateLimit-Limit" in response.headers
            assert "Retry-After" in response.headers

    def test_a_browser_route_is_refused_with_a_page(self):
        """The throttle answers the way every other refusal there does.

        Building the answer by hand, it returned an envelope wherever the
        request came from: an exhausted limit on ``GET /login`` put raw
        JSON in the browser, while a 404 on the same route rendered a
        page. The headers stay on either answer -- a browser ignores them,
        a proxy does not.
        """
        limiter = _limiter(allowed=False, remaining=0)

        app, _ = self._make_app(rate_limiter=limiter)
        with app.test_client() as client:
            response = client.get("/test")

        assert response.status_code == 429
        assert response.get_json() is None
        assert response.mimetype == "text/html"
        assert "Too many requests" in response.get_data(as_text=True)
        assert response.headers["Retry-After"] == "60"

    def test_the_refusal_reports_the_window_the_caller_actually_waits(self):
        """
        The numbers in the refusal, not merely their presence.

        Retry-After and the message are what a client obeys and what an
        operator reads. Swapping the pair on the way out -- "3600 per 3
        seconds", Retry-After 3 -- was invisible: the assertions above ask
        whether the headers exist, never what they say.
        """
        limiter = _limiter(allowed=False, remaining=0)
        app, _ = self._make_app(
            rate_limiter=limiter, rate_limits={"api.test": (3, 3600)}
        )

        with app.test_client() as client:
            response = client.get("/api/v1/test")

        assert response.headers["Retry-After"] == "3600"
        assert response.headers["X-RateLimit-Limit"] == "3"
        assert "3 per 3600 seconds" in response.get_json()["message"]
        # The refusal must not contradict itself. A body saying the quota
        # is spent beside a header saying the whole quota remains is the
        # same answer the after_request hook exists to prevent on somebody
        # else's 429 -- nothing was watching it on the throttle's own.
        assert response.headers["X-RateLimit-Remaining"] == "0"

    def test_an_application_configuring_no_default_gets_the_shipped_one(self):
        """
        The fallback pair is the shipped pair, and reaches the limiter.

        Two named constants stop the two literals drifting apart, but not
        a reader wired to the wrong one: DEFAULT_RATE_LIMIT read with
        FALLBACK_PERIOD beside it drops the ceiling from a hundred to
        sixty, and nothing in the suite went near the fallback at all --
        every other test in this file sets both values explicitly.
        """
        from link_shortener.web.middleware.rate_limit import RateLimitMiddleware

        limiter = _limiter()
        app = Flask(__name__)
        app.config["TESTING"] = True
        RateLimitMiddleware(app, limiter)

        @app.route("/test")
        def test_view():
            return "ok", 200

        with app.test_client() as client:
            client.get("/test")

        # Literals, not BaseConfig: those fields read the environment, so
        # comparing against them would pass on a machine that exports
        # DEFAULT_RATE_LIMIT. That the fallback matches what the profiles
        # ship is asserted where the environment can be detached, in
        # tests/unit/infrastructure/test_config/test_secure_defaults.py.
        _, limit, period = limiter.check.call_args[0]
        assert (limit, period) == (100, 60)

    def test_rate_limit_headers_added(self):
        """Normal response includes rate limit headers."""
        app, limiter = self._make_app()
        with app.test_client() as client:
            response = client.get("/test")
            assert response.headers.get("X-RateLimit-Limit") == "5"
            assert response.headers.get("X-RateLimit-Remaining") == "4"

    def test_custom_rate_limit_per_endpoint(self):
        """Custom per-endpoint rate limits are used when configured."""
        limiter = _limiter(remaining=9)

        # Use the endpoint name (view function name) as key
        app, _ = self._make_app(
            rate_limiter=limiter,
            rate_limits={"test_view": (10, 120)},
        )
        with app.test_client() as client:
            response = client.get("/test")
            assert response.status_code == 200
            assert response.headers.get("X-RateLimit-Limit") == "10"
            # The pair reaches the limiter unaltered. Narrowing the window
            # on the way through -- min(period, self.default_period) --
            # left every assertion in this file satisfied while the
            # registration limit went from three an hour to three a minute.
            _, limit, period = limiter.check.call_args[0]
            assert (limit, period) == (10, 120)

    def test_auth_disabled_skips_rate_limit(self):
        """Auth endpoints skip rate limiting when auth_disabled is True."""
        limiter = _limiter(allowed=False, remaining=0)

        app, _ = self._make_app(rate_limiter=limiter, auth_disabled=True)
        with app.test_client() as client:
            response = client.get("/auth/test")
            # Auth endpoint should skip rate limiting
            assert response.status_code == 200
            limiter.check.assert_not_called()

    def test_client_id_uses_ip_for_anonymous(self):
        """Anonymous user uses IP as client identifier."""
        limiter = _limiter()

        app, _ = self._make_app(rate_limiter=limiter)
        with app.test_client() as client:
            response = client.get("/test")
            call_args = limiter.check.call_args
            key = call_args[0][0]
            # Should not contain "user:" prefix
            assert "user:" not in key

    def test_key_includes_endpoint(self):
        """Rate limit key includes the endpoint name."""
        limiter = _limiter()

        app, _ = self._make_app(rate_limiter=limiter)
        with app.test_client() as client:
            client.get("/test")
            call_args = limiter.check.call_args
            key = call_args[0][0]
            assert "test_view" in key

    def test_an_auth_endpoint_is_throttled_unless_the_switch_says_otherwise(self):
        """
        The brute-force defence, asserted with the switch in its off state.

        The pytest-collected tree had no live auth throttle in it: the
        integration and e2e configurations set RATE_LIMIT_AUTH_DISABLED,
        and the unit one mocks the container, so its limiter is a
        MagicMock that allows everything. Dropping `self.auth_disabled
        and` from the skip left every collected test green with login
        answering without a limit; only the live run, which pytest does
        not collect, went red.
        """
        limiter = _limiter(allowed=False, remaining=0)
        app, _ = self._make_app(rate_limiter=limiter, auth_disabled=False)

        with app.test_client() as client:
            response = client.get("/auth/test")

        assert response.status_code == 429
        limiter.check.assert_called_once()

    def test_the_auth_switch_reaches_nothing_but_auth(self):
        """
        The development switch must not be a way to unthrottle everything.

        It is read as `auth_disabled and endpoint.startswith("auth.")`, and
        dropping the second half leaves it meaning "throttle nothing at
        all", on a setting the profiles ship as False precisely so that
        nobody inherits it. Two other tests notice by side effect of
        what they check -- test_quota_answers, through the headers it
        expects, and the end-to-end probe check -- but neither is a guard
        anybody put there for this.
        """
        limiter = _limiter(allowed=False, remaining=0)
        app, _ = self._make_app(rate_limiter=limiter, auth_disabled=True)

        with app.test_client() as client:
            response = client.get("/test")

        assert response.status_code == 429
        limiter.check.assert_called_once()

    def test_static_files_are_not_throttled(self):
        """
        The other half of the exemption, and the half nothing reached.

        No test in the suite requested a path under the static prefix, so
        deleting that half of the check left every test green while a page
        load spent a client's quota one stylesheet at a time.
        """
        limiter = _limiter(allowed=False, remaining=0)
        app, _ = self._make_app(rate_limiter=limiter)

        with app.test_client() as client:
            response = client.get("/static/nothing-here.css")

        # 404 because the file does not exist -- but 404 from the route,
        # not 429 from the throttle, and no headers to say a limit applied.
        assert response.status_code == 404
        assert "X-RateLimit-Limit" not in response.headers
        limiter.check.assert_not_called()

    def test_a_path_beginning_with_static_but_outside_it_is_throttled(self):
        """
        The prefix includes its slash, and dropping it opens a bypass.

        `/staticpage` is an ordinary short code. Testing the prefix without
        the trailing slash exempts it and everything else beginning
        "static" -- measured, two hundred and fifty requests and not one
        refusal. The test above cannot see it: `/static/nothing-here.css`
        is exempt under either reading.
        """
        limiter = _limiter(allowed=False, remaining=0)
        app, _ = self._make_app(rate_limiter=limiter)

        @app.route("/<code>", endpoint="redirect_to_original")
        def redirect_to_original(code):
            return "ok", 200

        with app.test_client() as client:
            response = client.get("/staticpage")

        assert response.status_code == 429
        limiter.check.assert_called_once()

    def test_the_probe_is_not_throttled(self):
        """
        A limiter refusing everything still leaves the probe answering 200.

        Reaches the exemption itself rather than the bookkeeping around it:
        reading request.path where the set holds endpoint names leaves
        every other test in this suite green while the orchestrator starts
        reading a busy service as a dead one. The other way to break it --
        renaming the view function the endpoint name is taken from -- this
        test cannot see, because it registers the route itself; that one
        belongs to the end-to-end check against the real application.
        """
        limiter = _limiter(allowed=False, remaining=0)
        app, _ = self._make_app(rate_limiter=limiter)

        @app.route("/health", endpoint="health")
        def health():
            return "ok", 200

        with app.test_client() as client:
            response = client.get("/health")

        assert response.status_code == 200
        assert "X-RateLimit-Limit" not in response.headers
        limiter.check.assert_not_called()

    def test_one_bucket_per_endpoint_not_per_path(self):
        """
        Every path an endpoint answers on shares that endpoint's quota.

        Putting request.path into the key turns "two hundred redirects a
        minute" into "two hundred per short code", which is no limit at all
        against somebody walking the code space. Measured: two hundred and
        fifty requests to two hundred and fifty codes, not one refusal.
        `test_key_includes_endpoint` cannot see it -- the endpoint is still
        in the key, with the path beside it.
        """
        limiter = _limiter()
        app, _ = self._make_app(rate_limiter=limiter)

        @app.route("/<code>", endpoint="redirect_to_original")
        def redirect_to_original(code):
            return "ok", 200

        with app.test_client() as client:
            client.get("/aaaaaa")
            client.get("/bbbbbb")

        first, second = (call[0][0] for call in limiter.check.call_args_list)
        assert first == second

    def test_a_head_request_is_counted_like_the_get_it_mirrors(self):
        """
        HEAD does the same work and must cost the same quota.

        Flask adds HEAD to every GET route, and the view runs in full: the
        code is looked up, the database is asked. Exempting it by method
        leaves the whole read surface unlimited to anyone who drops the
        body -- measured, two hundred and fifty HEADs and no refusal, where
        GET refused at fifty. No test in the suite sent one.
        """
        limiter = _limiter(allowed=False, remaining=0)
        app, _ = self._make_app(rate_limiter=limiter)

        with app.test_client() as client:
            response = client.head("/test")

        assert response.status_code == 429
        limiter.check.assert_called_once()

    def test_a_path_with_no_route_is_still_counted(self):
        """
        A request that matches nothing is still a request that costs work.

        Exempting them hands a scanner an unlimited channel, and takes
        every path with a trailing slash with it: those reach
        before_request with no endpoint at all, before the redirect.
        """
        limiter = _limiter(allowed=False, remaining=0)
        app, _ = self._make_app(rate_limiter=limiter)

        with app.test_client() as client:
            response = client.get("/no/such/thing")

        assert response.status_code == 429
        limiter.check.assert_called_once()

    def test_a_path_that_merely_begins_with_the_probes_name_is_throttled(self):
        """
        The exemption is by endpoint name, and by nothing that resembles it.

        `/healthy1` is a perfectly ordinary short code, and its path begins
        with the exempt endpoint's name. Deciding the exemption from the
        path in any prefix-shaped way hands every code starting "health" a
        complete bypass: measured, two hundred and fifty requests through
        a redirect limit of two hundred and not one 429.

        The test above cannot see this -- it asks about /health itself,
        which is exempt under either reading.
        """
        limiter = _limiter(allowed=False, remaining=0)
        app, _ = self._make_app(rate_limiter=limiter)

        @app.route("/<code>", endpoint="redirect_to_original")
        def redirect_to_original(code):
            return "ok", 200

        with app.test_client() as client:
            response = client.get("/healthy1")

        assert response.status_code == 429
        limiter.check.assert_called_once()

    def test_nothing_but_the_probe_is_exempt(self):
        """
        The exempt list is pinned to a literal, not merely searched.

        Asserting only that the probe is in it leaves the list free to
        grow, and an endpoint added here loses its throttle silently.
        `api.delete_link` quietly leaving the throttle is not a
        documentation problem.
        """
        assert EXEMPT_ENDPOINTS == frozenset({"health"})


class TestRateLimitTargets:
    """Tests for check_rate_limit_targets, the startup reachability check."""

    def _app_with(self, rate_limits):
        """
        Build an app carrying the given limits and one ordinary route.

        Args:
            rate_limits: Value for the RATE_LIMITS config key.

        Returns:
            The Flask app, routes registered, nothing checked yet.
        """
        app = Flask(__name__)
        app.config["RATE_LIMITS"] = rate_limits

        @app.route("/test")
        def test_view():
            return "ok", 200

        return app

    def test_a_reachable_endpoint_is_accepted(self):
        """
        The check passes what the throttle can actually reach.

        The list form is here on purpose. A value that came back from JSON
        or YAML is a list, not a tuple, and narrowing the accepted types to
        tuples alone stops a working configuration from booting -- which is
        worse than the ignored setting this check exists to prevent.
        """
        check_rate_limit_targets(self._app_with({"test_view": (10, 60)}))
        check_rate_limit_targets(self._app_with({"test_view": [10, 60]}))
        # One per window is the strictest setting that still means
        # something. Tightening the bound to `> 1` refuses it, and an
        # application that will not start on (1, 3600) is a worse outcome
        # than the ignored setting this check exists to prevent.
        check_rate_limit_targets(self._app_with({"test_view": (1, 1)}))

    def test_an_endpoint_answering_on_more_than_the_static_prefix_is_kept(self):
        """
        Only an endpoint served *entirely* from the static prefix is dead.

        One that also answers on an ordinary path is reached by the
        throttle on that path, so refusing its limit would refuse a
        configuration that works. Loosening `all` to `any` is otherwise a
        one-word change nothing objects to.
        """
        def serve_asset():
            return "ok", 200

        # The ordinary path is registered first on purpose. Collecting
        # only the last rule per endpoint -- routes[ep] = [rule] instead of
        # appending -- passes when the static one happens to come last.
        app = self._app_with({"assets": (10, 60)})
        app.add_url_rule("/logo.svg", "assets", serve_asset)
        app.add_url_rule("/static/logo.svg", "assets", serve_asset)

        check_rate_limit_targets(app)

    def test_an_exempt_endpoint_is_refused(self):
        """A limit on the probe never applies, so it is not accepted."""
        app = self._app_with({"health": (10, 5)})

        @app.route("/health", endpoint="health")
        def health():
            return "ok", 200

        with pytest.raises(ValueError) as exc_info:
            check_rate_limit_targets(app)

        assert "health" in str(exc_info.value)
        assert "EXEMPT_ENDPOINTS" in str(exc_info.value)

    def test_an_endpoint_nothing_answers_to_is_refused(self):
        """A misspelled name is as dead as an exempt one, and as quiet."""
        with pytest.raises(ValueError) as exc_info:
            check_rate_limit_targets(self._app_with({"api.crate_link": (5, 60)}))

        assert "api.crate_link" in str(exc_info.value)
        assert "no route answers" in str(exc_info.value)

    def test_a_static_route_is_refused(self):
        """
        The static prefix is refused a line before endpoint names are read.

        Flask registers the `static` endpoint on every app, so a limit put
        there looks perfectly plausible and does nothing at all.
        """
        with pytest.raises(ValueError) as exc_info:
            check_rate_limit_targets(self._app_with({"static": (1, 60)}))

        assert "static" in str(exc_info.value)
        assert "/static/" in str(exc_info.value)

    def test_a_static_route_under_another_name_is_refused_too(self):
        """
        The rule is where the endpoint answers, not what it is called.

        The real application carried two for a while: Flask's own `static`
        and a `frontend.static` from the blueprint, both over
        `/static/<path:filename>`. The blueprint's is gone -- one path
        cannot match two rules, so it was dead -- but the check must not
        start deciding by the name, or a blueprint that registers its own
        static route again would walk straight past it.
        """
        def serve_asset():
            return "ok", 200

        app = self._app_with({"frontend.static": (1, 60)})
        app.add_url_rule("/static/app.css", "frontend.static", serve_asset)

        with pytest.raises(ValueError) as exc_info:
            check_rate_limit_targets(app)

        assert "frontend.static" in str(exc_info.value)
        assert "/static/" in str(exc_info.value)

    def test_a_limit_that_is_not_a_pair_is_refused(self):
        """
        A malformed value breaks several ways, and the quiet ones are worst.

        Four of the nine below answer 500 from the endpoint -- including
        ("5", 60), which unpacks perfectly well and then fails inside the
        in-memory limiter comparing a str against an int. (0, 60) is the
        loudest: it refuses every request forever. Two are silent, and
        those are this defect again -- (5, -60) starts the window in the
        future so every recorded hit falls outside it, and an infinite
        limit simply never refuses. The two float pairs -- (5, 60.0) and
        (5, 0.5) -- are refused for a different reason again; see the
        docstring of _is_limit_pair.
        """
        values = (
            10, (5,), (5, 60, 1), ("5", 60), (0, 60), (5, -60),
            (5, 60.0), (float("inf"), 60), (5, 0.5),
        )
        for value in values:
            with pytest.raises(ValueError) as exc_info:
                check_rate_limit_targets(self._app_with({"test_view": value}))

            assert "test_view" in str(exc_info.value)
            assert "positive integers" in str(exc_info.value)

    def test_a_boolean_is_not_taken_for_a_limit(self):
        """
        True is an int in Python, and means something different everywhere.

        Against the in-memory limiter (True, 60) is one request per minute.
        Against Redis it is not a limit at all: redis-py refuses a bool
        outright, the limiter reads the error as an outage and fails open,
        and /health starts reporting rate_limiter: not_enforcing. Two
        backends, two wrong answers, neither of them the one written.
        """
        with pytest.raises(ValueError):
            check_rate_limit_targets(self._app_with({"test_view": (True, 60)}))

    def test_a_key_that_is_not_a_string_is_reported_not_raised_through(self):
        """
        The refusal has to survive the configuration it is refusing.

        Sorting the faults by the key itself raised TypeError the moment a
        non-string key stood beside a string one -- a traceback from inside
        the check, where the operator was owed the list of reasons.
        """
        with pytest.raises(ValueError) as exc_info:
            check_rate_limit_targets(
                self._app_with({None: (5, 60), "nope": (5, 60)})
            )

        assert "None" in str(exc_info.value)
        assert "nope" in str(exc_info.value)

    def test_a_rate_limits_that_is_not_a_mapping_is_refused(self):
        """A value nothing can be looked up in is refused where it is set."""
        with pytest.raises(ValueError) as exc_info:
            check_rate_limit_targets(self._app_with("not-a-dict"))

        assert "must be a dict" in str(exc_info.value)

    def test_none_means_no_per_endpoint_limits_to_both_halves(self):
        """
        The two readers of this setting used to disagree about None.

        The check normalised it to an empty mapping, so startup passed; the
        middleware read `... .get(key, {})`, got None back, and failed on
        the lookup -- a 500 from whichever endpoint was asked for first,
        one request after the setting that caused it.
        """
        from link_shortener.web.middleware.rate_limit import RateLimitMiddleware

        check_rate_limit_targets(self._app_with(None))

        app = self._app_with(None)
        app.config["DEFAULT_RATE_LIMIT"] = 5
        app.config["DEFAULT_RATE_LIMIT_PERIOD"] = 60
        RateLimitMiddleware(app, _limiter())

        with app.test_client() as client:
            response = client.get("/test")

        assert response.status_code == 200

    def test_the_shipped_config_sets_no_limit_on_an_exempt_endpoint(self):
        """
        The shipped settings and the exempt list do not contradict.

        Says out loud what would otherwise surface only as every
        application-building test failing at once. That the settings reach
        real routes is asserted against the real application in
        tests/integration/web/middleware/test_rate_limit_targets.py -- it
        needs a URL map, which this test has no business building.
        """
        assert not set(BaseConfig.RATE_LIMITS) & EXEMPT_ENDPOINTS

