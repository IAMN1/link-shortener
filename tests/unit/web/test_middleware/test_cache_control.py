"""
Tests for the private-cache middleware.

It exists because of a measurement rather than a theory: signed in, open
the dashboard, sign out, press Back -- and the browser redrew the previous
account's dashboard out of its own cache, address and links included, with
no request reaching the service. The session was already gone, so reloading
that URL landed on ``/login``; the picture came from the HTTP cache, which
only a header on the original response can speak to.

Two behaviours are worth as much as the header itself and are checked here:
an anonymous response must not be marked, or the landing page and the
short-link redirects stop being cacheable for everyone; and a static file
must not be marked even for a signed-in visitor, or the stylesheet, the
font and the vendored navigation library are re-fetched on every
navigation, which is a quarter of a megabyte to protect files handed to
anyone who asks.
"""

import pathlib

import pytest
from flask import Flask, g

import link_shortener.web
from link_shortener.web.middleware.cache_control import PrivateCacheMiddleware


STATIC = pathlib.Path(link_shortener.web.__file__).parent / "static"


@pytest.fixture
def app():
    """
    A bare application carrying the middleware and nothing else.

    ``current_user`` is set from a query parameter so one client can be
    both callers; the real value comes from the authentication middleware,
    which is not what is under test here.
    """
    from flask import request

    application = Flask(__name__, static_folder=str(STATIC))

    @application.before_request
    def pretend_authentication():
        g.current_user = object() if request.args.get("signed_in") else None

    PrivateCacheMiddleware(application)

    @application.route("/page")
    def page():
        return "a page"

    return application


@pytest.fixture
def client(app):
    return app.test_client()


class TestAnAccountsResponsesAreNotStored:

    def test_a_signed_in_response_says_no_store(self, client):
        response = client.get("/page?signed_in=1")

        assert response.headers.get("Cache-Control") == "no-store"

    def test_an_anonymous_response_is_left_alone(self, client):
        """
        The landing page, the API documentation and the redirects carry
        nothing personal, and they are the ones worth caching. Marking
        them would cost every anonymous visitor a fetch per page for no
        gain in privacy.
        """
        response = client.get("/page")

        assert "no-store" not in (response.headers.get("Cache-Control") or "")


class TestStaticFilesStayCacheable:

    def test_a_static_file_is_not_marked_for_a_signed_in_caller(self, client):
        """
        The stylesheet is the same bytes for everyone and is asked for on
        every page. Marked `no-store` it would be fetched again on every
        navigation -- the exact cost this middleware is not worth paying.
        """
        response = client.get("/static/css/main.css?signed_in=1")

        assert response.status_code == 200
        assert "no-store" not in (response.headers.get("Cache-Control") or "")

    def test_the_vendored_navigation_library_stays_cacheable_too(self, client):
        """
        Named separately because it is the largest single asset the
        service sends, and because re-fetching it on every navigation
        would defeat the point of navigating without a reload.
        """
        response = client.get(
            "/static/vendor/turbo-8.0.23.js?signed_in=1")

        assert response.status_code == 200
        assert "no-store" not in (response.headers.get("Cache-Control") or "")


class TestTheHookCannotBreakTheResponse:

    def test_a_request_that_never_reached_authentication_is_survivable(self):
        """
        ``g.current_user`` is set by the authentication middleware on every
        request, but an error raised before it runs leaves the attribute
        absent entirely. The hook must read that as "anonymous" rather
        than raise inside ``after_request`` -- where no error handler
        covers it, and where Flask re-raises under TESTING.
        """
        application = Flask(__name__)
        PrivateCacheMiddleware(application)

        @application.route("/bare")
        def bare():
            return "no authentication ran"

        response = application.test_client().get("/bare")

        assert response.status_code == 200
        assert "no-store" not in (response.headers.get("Cache-Control") or "")
