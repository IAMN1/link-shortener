"""
Which refusals the throttle gets to count.

Flask runs ``before_request`` hooks in the order they were registered, so
whichever middleware answers first decides what the ones behind it ever
see. With CSRF registered ahead of the limiter, every request CSRF refused
was a request the limiter never counted -- and CSRF refuses on the mere
presence of an auth cookie, not on a valid one. Sending
``access_token=anything`` was therefore enough to be exempt from the rate
limits entirely, no account required.

The limit is made small here rather than the requests made many: the
default is a hundred a minute, and a test that sends a hundred and one
requests measures patience.
"""

import pytest

from link_shortener.web.app_factory import create_app

from tests.integration.conftest import IntegrationTestConfig


LIMIT = 5


@pytest.fixture()
def throttled_app():
    """
    An application whose default limit is small enough to reach.

    Declared on a subclass rather than assigned onto the shared config,
    which would leak into every later test.

    Yields:
        A Flask app with a seeded database and a five-per-minute limit on
        the endpoint these tests hammer.
    """
    class ThrottledConfig(IntegrationTestConfig):
        # The endpoint's own entry, not DEFAULT_RATE_LIMIT: the table
        # overrides the default, so lowering the default alone leaves this
        # route at its shipped thirty a minute and the test measures
        # nothing.
        RATE_LIMITS = {"api.create_short_link": (LIMIT, 60)}

    application = create_app(config=ThrottledConfig())
    application.config["TESTING"] = True

    with application.app_context():
        db_manager = application.container.get_db_manager()
        db_manager.create_tables()
        from link_shortener.infrastructure.database.seed import seed_base_roles
        with db_manager.session() as session:
            seed_base_roles(session)

    yield application

    with application.app_context():
        application.container.close()


def post_many(app, address, cookies, count):
    """
    Send the same write repeatedly from one address and collect the codes.

    Args:
        app: Application under test.
        address: Value to report as ``REMOTE_ADDR``; the limiter counts
            anonymous callers by address, so each scenario needs its own.
        cookies: Cookies the client should carry.
        count: How many requests to send.

    Returns:
        List of status codes, in order.
    """
    client = app.test_client()
    client.environ_base = dict(client.environ_base)
    client.environ_base["REMOTE_ADDR"] = address
    for name, value in cookies.items():
        client.set_cookie(name, value, domain="localhost")

    return [
        client.post(
            "/api/v1/shorten", json={"url": "https://example.com"}
        ).status_code
        for _ in range(count)
    ]


class TestARefusedWriteIsStillCounted:

    def test_a_cookie_that_is_not_a_session_does_not_lift_the_limit(
        self, throttled_app
    ):
        # The cookie is a made-up string: no account, no session, nothing
        # that any authentication step would accept. Before the ordering
        # was fixed this bought exemption from the limits -- measured on
        # the default settings, 60 requests, 60 refusals, not one 429.
        codes = post_many(
            throttled_app,
            "10.9.0.1",
            {"access_token": "not-a-real-token"},
            LIMIT + 3,
        )

        # CSRF still does its job: the write is refused, every time.
        assert codes[:LIMIT] == [403] * LIMIT
        # And the refusals were counted, so the limit arrives on schedule.
        assert codes[LIMIT:] == [429] * 3

    def test_an_anonymous_caller_is_throttled_as_before(self, throttled_app):
        # The other side of the same ordering: moving the limiter earlier
        # must not stop it counting the requests it always counted. No
        # cookie, so CSRF lets these through to the endpoint.
        codes = post_many(throttled_app, "10.9.0.2", {}, LIMIT + 2)

        assert 429 not in codes[:LIMIT]
        assert codes[LIMIT:] == [429] * 2

    def test_a_read_is_not_charged_to_the_write_limit_by_mistake(
        self, throttled_app
    ):
        # Guards against fixing the ordering by throttling everything: the
        # probe is exempt and stays exempt however many writes the same
        # address has already spent.
        post_many(
            throttled_app,
            "10.9.0.3",
            {"access_token": "not-a-real-token"},
            LIMIT + 3,
        )

        client = throttled_app.test_client()
        client.environ_base = dict(client.environ_base)
        client.environ_base["REMOTE_ADDR"] = "10.9.0.3"

        assert client.get("/health").status_code == 200


class TestTheRefusalLooksLikeTheRouteItCameFrom:
    """A browser route is refused with a page, an API route with JSON.

    Without this, ``GET /login`` on an exhausted limit answers
    ``429 application/json``, while every other refusal on that same route
    -- 404, 500, an expired session -- renders ``error.html``. The
    throttle built its answer by hand and never asked what the caller
    wanted.

    Driven against the real application, so the real template is the one
    that renders: the unit test beside this uses a stub, and a layout that
    fails to build a URL would pass there and 500 here.
    """

    @pytest.fixture()
    def html_throttled_app(self):
        """An app whose login *page* is limited to one request."""
        class PageThrottledConfig(IntegrationTestConfig):
            RATE_LIMITS = {"frontend.login_page": (1, 60)}

        application = create_app(config=PageThrottledConfig())
        application.config["TESTING"] = True
        yield application
        with application.app_context():
            application.container.close()

    def test_a_page_route_answers_with_a_page(self, html_throttled_app):
        client = html_throttled_app.test_client()

        client.get("/login")
        response = client.get("/login")

        assert response.status_code == 429
        assert response.mimetype == "text/html"
        body = response.get_data(as_text=True)
        assert "Too many requests" in body
        # The real template, not merely any HTML: it extends the site
        # layout, and a layout that cannot build one of its URLs answers
        # 500 instead.
        assert "<html" in body.lower()
        assert response.headers["Retry-After"] == "60"

    def test_an_api_route_still_answers_with_the_envelope(self, throttled_app):
        client = throttled_app.test_client()

        for _ in range(LIMIT + 1):
            response = client.post(
                "/api/v1/shorten", json={"url": "https://example.com/x"}
            )

        assert response.status_code == 429
        assert response.get_json()["error"] == "RATE_LIMIT_EXCEEDED"
