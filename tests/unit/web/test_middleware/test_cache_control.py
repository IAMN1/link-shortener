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


class TestAPageSaysWhatItWasBuiltFrom:
    """
    A cacheable page that is built from the request has to say so.

    Measured before this existed: `/` renders `data-theme="dark"`, or
    nothing at all, purely from a cookie; it carries no `Cache-Control`,
    and it said it varied by `Accept-Encoding` alone. Every ingredient of
    the fault was already in place -- a page that differs per visitor, no
    instruction not to store it, and no mention of what it differs by.
    Adding the language to the same page is what made it worth fixing:
    the wrong colour scheme is a nuisance, a whole page in a language the
    reader does not have is not.
    """

    def test_a_page_says_it_varies_by_the_cookie(self, client):
        response = client.get("/page")

        assert "Cookie" in (response.headers.get("Vary") or "")

    def test_a_page_says_it_varies_by_the_declared_language(self, client):
        """
        Named as well as the cookie, because the language is negotiated
        from the header whenever no cookie has been set -- which is the
        state every first visit is in. A cache told about the cookie alone
        would be free to answer an English browser out of what it stored
        for a Russian one.
        """
        response = client.get("/page")

        assert "Accept-Language" in (response.headers.get("Vary") or "")

    def test_a_redirect_is_not_made_to_vary(self, app):
        """
        The short-link redirects are the most cacheable thing the service
        has and are built from no cookie and no language at all. Marking
        them would spend the caching this middleware exists to protect.
        """
        from flask import redirect

        @app.route("/go")
        def go():
            return redirect("https://example.com")

        response = app.test_client().get("/go")

        assert "Cookie" not in (response.headers.get("Vary") or "")

    def test_a_static_file_is_not_made_to_vary(self, client):
        response = client.get("/static/css/main.css")

        assert response.status_code == 200
        assert "Cookie" not in (response.headers.get("Vary") or "")


class TestAnEnvelopeSaysItToo:
    """
    The API answers in a language now, so its answers vary as pages do.

    ``message`` used to be one English sentence per refusal, the same for
    everybody, and an anonymous ``/api/`` answer was safely cacheable as
    it stood. It is translated by the same cookie the pages are, and a
    shared cache holding one caller's ``"Ссылка не найдена"`` would hand
    it to the next caller regardless of what they asked for.
    """

    @pytest.fixture
    def envelope_app(self, app):
        """The same bare app, with a route that answers JSON."""
        from flask import jsonify

        @app.route("/api/v1/thing")
        def thing():
            return jsonify({"error": "LINK_NOT_FOUND", "message": "Link not found"}), 404

        return app

    def test_a_json_answer_says_it_varies_by_the_cookie(self, envelope_app):
        response = envelope_app.test_client().get("/api/v1/thing")

        assert "Cookie" in (response.headers.get("Vary") or "")

    def test_a_json_answer_says_it_varies_by_the_declared_language(
        self, envelope_app
    ):
        response = envelope_app.test_client().get("/api/v1/thing")

        assert "Accept-Language" in (response.headers.get("Vary") or "")

    def test_a_refusal_is_covered_and_not_only_a_success(self, envelope_app):
        """
        Deliberately a 404. The refusals are exactly the answers whose
        ``message`` is a sentence a person reads, and a rule written for
        2xx alone -- which is what the page rule is -- would leave every
        one of them unmarked.
        """
        response = envelope_app.test_client().get("/api/v1/thing")

        assert response.status_code == 404
        assert "Cookie" in (response.headers.get("Vary") or "")


class TestTheTwoHooksThatWriteVaryDoNotEraseEachOther:
    """
    Both hooks write ``Vary``, and they run one after the other.

    Flask runs ``after_request`` in the reverse of registration order, and
    compression is registered first, so it writes last -- onto a header
    this middleware has already set. Written with ``headers.setdefault`` it
    would find the header present and say nothing, dropping
    ``Accept-Encoding`` from a response that really does vary by it, and a
    shared cache would then hand a gzipped body to a client that never
    asked for one. Written with plain assignment it would drop the other
    hook's names instead. Only ``vary.add`` on both sides survives either
    order.
    """

    @pytest.fixture
    def both(self):
        """An application carrying both hooks, registered as the app factory does."""
        from link_shortener.web.middleware.compression import CompressionMiddleware

        application = Flask(__name__, static_folder=str(STATIC))

        @application.before_request
        def anonymous():
            g.current_user = None

        # Same order as `create_app`: compression first, so it runs last.
        CompressionMiddleware(application)
        PrivateCacheMiddleware(application)

        @application.route("/page")
        def page():
            return "a page"

        return application

    def test_every_name_survives(self, both):
        response = both.test_client().get(
            "/page", headers={"Accept-Encoding": "gzip"}
        )

        vary = response.headers.get("Vary") or ""
        for name in ("Accept-Encoding", "Cookie", "Accept-Language"):
            assert name in vary, f"{name} was erased from Vary: {vary!r}"

    def test_no_name_is_written_twice(self, both):
        """
        ``vary.add`` is idempotent, and a header reading
        ``Accept-Encoding, Accept-Encoding`` would be the sign that
        something started appending instead.
        """
        response = both.test_client().get(
            "/page", headers={"Accept-Encoding": "gzip"}
        )

        names = [n.strip() for n in (response.headers.get("Vary") or "").split(",")]

        assert len(names) == len(set(names)), f"Vary repeats itself: {names}"


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
