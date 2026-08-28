from flask import (
    Flask, g, jsonify, make_response, request
)
from flask_babel import ngettext

from link_shortener.application import RateLimiter
from link_shortener.web.responses import error_page, wants_html
from link_shortener.web.schemas.error import ErrorResponse
from link_shortener.web.security.context import get_client_ip
from link_shortener.web.middleware.hooks import response_hook
from link_shortener.infrastructure.logging.handlers.logger.null_logger import (
    NullLogger,
)


EXEMPT_ENDPOINTS = frozenset({"health"})
"""Endpoints that must answer regardless of how often they are asked."""

STATIC_PREFIX = "/static/"
"""Path prefix served without throttling, checked before the endpoint name."""

FALLBACK_LIMIT = 100
FALLBACK_PERIOD = 60
"""
What an application that configures neither default gets.

Matches the shipped ``DEFAULT_RATE_LIMIT`` and ``DEFAULT_RATE_LIMIT_PERIOD``
so that an application built without them is bounded the same way as one
built with the profile that names them.
"""


def check_rate_limit_targets(app: Flask) -> None:
    """
    Refuse a ``RATE_LIMITS`` entry the throttle can never apply.

    An entry only applies if the throttle gets as far as looking it up,
    and three things stop it permanently: no route answers to that name,
    the name is exempt, or every route it answers on sits under the static
    prefix. In all three the setting reads like a live limit and throttles
    nothing.

    ``RATE_LIMIT_AUTH_DISABLED`` is deliberately not refused: switching
    every ``auth.*`` limit off at run time is how a development run stops
    locking itself out, and the integration and e2e configurations set it.

    Values are checked too. A value the limiter cannot use -- ``10``,
    ``(5,)``, ``("5", 60)`` -- raises inside ``before_request`` and answers
    500 for that endpoint; a zero limit refuses every request forever; a
    negative period puts the window's start in the future, so nothing is
    throttled at all. ``("5", 60)`` is worth naming because it fails
    against the in-memory limiter and not against Redis, whose script
    coerces the number.

    Held against the URL map, so a misspelled name is caught by the same
    check. Call it once every route is registered: the middleware is
    installed before the first blueprint.

    ``DEFAULT_RATE_LIMIT`` and ``DEFAULT_RATE_LIMIT_PERIOD`` are not
    checked here even though they bound every route this table does not
    name -- ``BaseConfig.validate`` already refuses a non-positive one,
    and a second opinion in another layer is free to drift from the first.

    Args:
        app: Flask application with every route already registered.

    Raises:
        ValueError: If ``RATE_LIMITS`` is not a mapping, or if any entry
            is unusable -- naming each one and why.
    """
    rate_limits = app.config.get("RATE_LIMITS")
    if rate_limits is None:
        rate_limits = {}
    if not isinstance(rate_limits, dict):
        raise ValueError(
            f"RATE_LIMITS must be a dict of endpoint -> (limit, period), "
            f"got {type(rate_limits).__name__}"
        )

    routes: dict = {}
    for rule in app.url_map.iter_rules():
        routes.setdefault(rule.endpoint, []).append(rule.rule)

    faults = {}
    for endpoint, limit in rate_limits.items():
        paths = routes.get(endpoint)
        if paths is None:
            faults[endpoint] = "no route answers to that name"
        elif endpoint in EXEMPT_ENDPOINTS:
            faults[endpoint] = "listed in EXEMPT_ENDPOINTS"
        elif all(path.startswith(STATIC_PREFIX) for path in paths):
            faults[endpoint] = f"served from {STATIC_PREFIX}, never throttled"
        elif not _is_limit_pair(limit):
            faults[endpoint] = (
                f"{limit!r} is not a (limit, period_seconds) pair of "
                "positive integers"
            )

    if faults:
        # Sorted by repr, not by the key itself: a non-string key is
        # exactly the sort of configuration this refuses, and sorting it
        # against the strings beside it raised TypeError from inside the
        # check -- a traceback where the operator was owed a list of
        # reasons.
        listed = "; ".join(
            f"{endpoint} ({reason})"
            for endpoint, reason in sorted(faults.items(), key=lambda f: repr(f[0]))
        )
        raise ValueError(f"RATE_LIMITS carries entries that cannot work: {listed}")


def _is_limit_pair(limit: object) -> bool:
    """
    Report whether a configured value is a usable ``(limit, period)``.

    A list is accepted beside a tuple. ``[5, 60]`` is the same pair spelt
    differently and the middleware unpacks it just as happily, so refusing
    it would refuse a configuration that works -- and an application that
    will not start on a correct setting is worse than the ignored setting
    this check exists to prevent.

    ``bool`` is refused although it is an ``int``. ``(True, 60)`` means
    one request a minute against the in-memory limiter, and against Redis
    it means no limit at all: redis-py refuses a bool, the limiter reads
    the error as an outage and fails open, and the health endpoint starts
    reporting ``rate_limiter: not_enforcing``. Two backends, two answers,
    neither of them the one written.

    ``float`` is refused although ``(5, 60.0)`` demonstrably works on both
    backends. The line is drawn at ``int`` because that is the boundary
    that can be stated exactly, and one step away the failures are ugly:
    ``inf`` never refuses anything, and with ``0.5`` the Redis script adds
    to the set and then fails its own ``EXPIRE``, so the key is left
    without one -- not growing, since the window is still trimmed, but
    immortal, and there is one of them per client -- while the health
    endpoint flaps between enforcing and not_enforcing and every allowed
    request logs an error.
    This is the one place the check refuses a working value; it is
    deliberate, and it is loud -- the message names the value and the
    rule, which costs an operator a minute rather than an outage.

    Args:
        limit: Value taken from ``RATE_LIMITS``.

    Returns:
        True if it is a two-element sequence of positive integers.
    """
    if not isinstance(limit, (tuple, list)) or len(limit) != 2:
        return False
    return all(
        isinstance(part, int) and not isinstance(part, bool) and part > 0
        for part in limit
    )


class RateLimitMiddleware:
    """
    Applies rate limiting to all incoming requests.

    Limits are defined per endpoint; endpoints without specific
    configuration use the default limits. When exceeded, a 429 response
    with standard rate-limit headers is returned.

    Two kinds of request are let through untouched: anything under the
    static prefix, and the endpoints named in ``EXEMPT_ENDPOINTS``. Both
    are checked before any limit is looked up, which is why a limit
    configured for either would be dead -- see ``check_rate_limit_targets``.
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
        self.default_limit = app.config.get("DEFAULT_RATE_LIMIT", FALLBACK_LIMIT)
        self.default_period = app.config.get(
            "DEFAULT_RATE_LIMIT_PERIOD", FALLBACK_PERIOD
        )

        # `or {}` rather than a default: RATE_LIMITS set to None passed the
        # startup check and then failed here, on the first request, as a
        # 500 from whichever endpoint was asked for first.
        self.rate_limits = app.config.get("RATE_LIMITS") or {}
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
            if (
                request.path.startswith(STATIC_PREFIX)
                or request.endpoint in EXEMPT_ENDPOINTS
            ):
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
                # The same envelope every other refusal answers in, and the
                # one the OpenAPI document declares for the 429 it merges
                # into every operation. Built by hand, this answer
                # carried neither `details` nor `timestamp` while the
                # document promised both -- and the guest-quota 429 beside
                # it, which goes through the error handler, did carry them:
                # one API, two shapes for one status.
                #
                # `retry_after` stays on top of the envelope rather than in
                # place of it. It is also the `Retry-After` header below,
                # and a client that reads the body for it exists as surely
                # as one that reads the header.
                body = ErrorResponse(
                    error="RATE_LIMIT_EXCEEDED",
                    # `ngettext` rather than `gettext`, on `period`: the
                    # sentence ends in a count of seconds, and Russian
                    # takes three forms for it -- "1 секунду", "3
                    # секунды", "60 секунд". A single form gets two of
                    # those three wrong, and 60 is the value it ships
                    # with.
                    message=ngettext(
                        "Too many requests. Limit %(limit)s per %(period)s second.",
                        "Too many requests. Limit %(limit)s per %(period)s seconds.",
                        period,
                        limit=limit,
                        period=period,
                    ),
                ).model_dump()
                body["retry_after"] = period
                # Answered the way every other refusal on this route is
                # answered. Built by hand, the throttle returned JSON
                # wherever the request came from: `GET /login` on an
                # exhausted limit put a raw envelope in the browser, while
                # a 404 or a 500 on the same route rendered `error.html`.
                # The headers below are set either way -- a browser does
                # not read them, but a proxy and a crawler do.
                response = None
                if wants_html():
                    try:
                        response = make_response(
                            error_page(
                                "RATE_LIMIT_EXCEEDED", body["message"], 429
                            )
                        )
                    except Exception as e:
                        # A page that will not render must not cost the
                        # caller the refusal itself: unhandled, this comes
                        # out as 500 with no Retry-After, so a client that
                        # obeys the header has nothing to obey. The
                        # envelope is a worse answer for a browser and a
                        # far better one than a 500.
                        self.logger.error(
                            "Rate limit page failed to render", error=str(e)
                        )
                if response is None:
                    response = jsonify(body)
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
