"""
Two middlewares the factory installs, asked through the factory.

Both have unit tests, and both of those build a bare `Flask` app and
install the middleware on it by hand. That holds what the middleware does
and says nothing about whether the application under test has it: deleting
`CompressionMiddleware(app)` from `app_factory` leaves the whole tree green
-- measured -- and the service ships without compression, which is the one
thing standing between a 211 KB script and the browser, since nothing in
front of this application compresses anything.

`RequestLoggingMiddleware` is the same shape of gap and costs more when it
opens: `g.request_id` is what ties a journal line to the request that
produced it, and every line written below is bound from it.

So these ask the built application, not a fixture that installs the thing
being tested.
"""

from unittest.mock import patch


class TestTheResponseComesBackCompressed:

    def test_a_large_text_response_is_gzipped(self, app):
        """
        Asked of a body over the threshold, with the header a browser
        sends. Below `MINIMUM_BYTES` the middleware deliberately does
        nothing, so a small answer cannot tell an installed middleware
        from an absent one.
        """
        answer = app.test_client().get(
            "/api/openapi.json", headers={"Accept-Encoding": "gzip"}
        )

        assert answer.status_code == 200
        assert len(answer.get_data()) > 1024, "the premise: a body worth compressing"
        assert answer.headers.get("Content-Encoding") == "gzip"

    def test_a_caller_that_did_not_ask_gets_it_uncompressed(self, app):
        """The other half: the header is what decides, not the size."""
        answer = app.test_client().get(
            "/api/openapi.json", headers={"Accept-Encoding": "identity"}
        )

        assert answer.status_code == 200
        assert "Content-Encoding" not in answer.headers


class TestEveryRequestCarriesAnIdentifier:
    """
    Observed through the journal line the middleware writes, not through
    a route added here: the application under test has already served a
    request, and Flask refuses a route registered after that. Patched on
    the class of the logger the middleware holds, because it binds its
    context first and `bind` answers with a new logger -- patching the
    instance replaces a method nobody calls.
    """

    @staticmethod
    def _lines(app, path, times=1):
        """Every "Request started" line one or more requests produce."""
        middleware_logger = app.container.get_logger(
            "link_shortener.web.middleware.request_logging"
        )
        written = []

        def remember(self, event, **fields):
            if event in ("Request started", "Request completed"):
                written.append((event, fields))

        with patch.object(
            type(middleware_logger), "info", autospec=True, side_effect=remember
        ):
            client = app.test_client()
            for _ in range(times):
                client.get(path)
        return written

    def test_the_hook_ran_and_left_an_id_behind(self, app):
        """
        `g.request_id` is what every journal line of a request is bound
        from, so a middleware that is not installed leaves an
        investigation with no way to gather the lines of one request.
        """
        written = self._lines(app, "/api/openapi.json")

        started = [f for event, f in written if event == "Request started"]
        assert started, "the middleware wrote nothing for this request"
        assert len(started[0]["request_id"]) == 10, started[0]

    def test_the_two_lines_of_one_request_carry_the_same_id(self, app):
        """The pair is what makes the id worth having."""
        written = self._lines(app, "/api/openapi.json")
        ids = {fields["request_id"] for _, fields in written}

        assert len(written) == 2, written
        assert len(ids) == 1, written

    def test_two_requests_get_two_identifiers(self, app):
        """An id that never changes ties every line to every request."""
        written = self._lines(app, "/api/openapi.json", times=2)
        started = [f["request_id"] for e, f in written if e == "Request started"]

        assert len(started) == 2
        assert len(set(started)) == 2, started

    def test_a_static_file_is_left_alone(self, app):
        """
        The middleware returns early for `/static/`, which is what keeps
        a page load of a dozen assets out of the journal. The early
        return is one line, and reverting it is silent.
        """
        written = self._lines(app, "/static/css/main.css")

        assert written == [], written
