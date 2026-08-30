"""
Tests for the journal line that opens every request.

That line carries the address the request came from, and so does every
line the use cases write under the same ``request_id`` -- bound there
from ``RequestContext``, which asks ``get_client_ip()``. Written from
``request.remote_addr`` instead, this one named the connection's far
end, which behind a proxy is the proxy: one field, one file, one
request, two answers.

It also split a search. ``GET /api/v1/journals/application`` matches
``remote_addr`` exactly, so an investigation into one client was handed
the work its requests did and not the requests that carried it, and a
search for the proxy's own address answered with everything.
"""

from flask import g

from link_shortener.web.security.context import create_request_context


PROXY = "10.0.0.9"
REAL_CLIENT = "198.51.100.7"
STRANGER = "203.0.113.4"


def _started(test_logger):
    """The fields of the ``Request started`` line, or ``None``."""

    for _level, message, fields in test_logger.messages:
        if message == "Request started":
            return fields
    return None


def test_request_logging(client, test_logger):
    """Request should be logged with start and completion messages."""


    response = client.get("/health")

    assert response.status_code == 200
    # Check that test_logger.messages has the expected entries
    started = any(msg[1] == "Request started" for msg in test_logger.messages)
    completed = any(msg[1] == "Request completed" for msg in test_logger.messages)
    assert started, "Message 'Request started' not found"
    assert completed, "Message 'Request completed' not found"


class TestTheAddressTheOpeningLineCarries:
    """Which of the two addresses in play reaches the journal."""

    def test_behind_a_trusted_proxy_the_client_is_named(
        self, app, client, test_logger
    ):
        """Not the proxy -- every request through it would look alike."""

        app.config["TRUSTED_PROXIES"] = [PROXY]

        response = client.get(
            "/health",
            headers={"X-Forwarded-For": f"1.2.3.4, {REAL_CLIENT}"},
            environ_base={"REMOTE_ADDR": PROXY},
        )

        assert response.status_code == 200
        assert _started(test_logger)["remote_addr"] == REAL_CLIENT

    def test_a_header_from_an_untrusted_source_is_ignored(
        self, app, client, test_logger
    ):
        """Otherwise a caller writes their own address into the journal."""

        app.config["TRUSTED_PROXIES"] = [PROXY]

        client.get(
            "/health",
            headers={"X-Forwarded-For": STRANGER},
            environ_base={"REMOTE_ADDR": REAL_CLIENT},
        )

        assert _started(test_logger)["remote_addr"] == REAL_CLIENT

    def test_the_line_agrees_with_the_context_the_rest_of_the_request_uses(
        self, app, client, test_logger
    ):
        """
        The two writers of this field, compared inside one request.

        The middleware writes it from its own hook; everything below the
        controllers writes it from the ``RequestContext`` built for the
        same request. Reading the second one here rather than asserting a
        literal is what makes this a comparison of the two paths and not
        of one path with itself -- the defect was that they disagreed.
        """

        app.config["TRUSTED_PROXIES"] = [PROXY]
        from_context = []

        @app.before_request
        def capture():
            g.request_id = getattr(g, "request_id", "")
            from_context.append(create_request_context().remote_addr)

        client.get(
            "/health",
            headers={"X-Forwarded-For": f"1.2.3.4, {REAL_CLIENT}"},
            environ_base={"REMOTE_ADDR": PROXY},
        )

        assert from_context == [REAL_CLIENT]
        assert _started(test_logger)["remote_addr"] == from_context[0]
