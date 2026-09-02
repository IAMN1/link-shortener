"""Which ``Host`` values reach a view, and which are refused before one does.

Flask serves whatever ``Host`` it is handed. For a framework that is
right; for a deployment it is a door left open -- a name somebody else
pointed at this address is answered exactly as the configured one is.

Nothing in this application reads ``request.host`` today, and ``short_url``
is built from ``BASE_URL``, so the door leads nowhere yet. That is the
argument for shutting it now rather than after: a password-reset link or a
cache key built from an attacker's ``Host`` is one ordinary-looking commit
away, in a file that will know nothing about this one.

The default is empty, and an empty list means "answer to anything" -- which
is what the service has always done. So the first thing held here is that
the default changes nothing.
"""

import pytest
from flask import Flask

from link_shortener.web.middleware.host_check import (
    HostCheckMiddleware, normalise_host,
)


class SilentLogger:
    """A logger that keeps what it was told instead of writing it.

    Attributes:
        warnings: ``(event, fields)`` pairs, in order.
    """

    def __init__(self):
        self.warnings: list = []

    def warning(self, event, **fields):
        """Record a warning."""
        self.warnings.append((event, fields))

    def info(self, event, **fields):
        """Ignored: nothing under test writes one."""

    def error(self, event, **fields):
        """Ignored: nothing under test writes one."""

    def debug(self, event, **fields):
        """Ignored: nothing under test writes one."""

    def bind(self, **fields):
        """Answer with the same object, so records stay visible."""
        return self


def build(allowed):
    """
    An application carrying the middleware and one route.

    Args:
        allowed: What ``ALLOWED_HOSTS`` is set to.

    Returns:
        A ``(client, logger)`` pair.
    """
    app = Flask(__name__)
    app.config["ALLOWED_HOSTS"] = allowed
    logger = SilentLogger()
    HostCheckMiddleware(app, logger)

    @app.route("/page")
    def page():
        return "a page"

    return app.test_client(), logger


class TestAnEmptyListChangesNothing:
    """The default, which every existing deployment is on."""

    def test_any_host_is_served(self):
        """What the service did before this middleware existed."""
        client, _ = build([])

        assert client.get("/page", headers={"Host": "anything.example"}).status_code == 200

    def test_no_hook_is_registered_at_all(self):
        """Not merely permissive: absent.

        A hook that runs on every request to decide nothing is a cost a
        deployment that turned this off should not pay.
        """
        app = Flask(__name__)
        app.config["ALLOWED_HOSTS"] = []
        before = len(app.before_request_funcs.get(None, []))

        HostCheckMiddleware(app, SilentLogger())

        assert len(app.before_request_funcs.get(None, [])) == before

    def test_a_missing_setting_is_read_as_empty(self):
        """A configuration built in code may not carry the key at all."""
        app = Flask(__name__)
        logger = SilentLogger()

        HostCheckMiddleware(app, logger)

        assert app.before_request_funcs.get(None, []) == []


class TestANamedListShutsTheDoor:
    """What happens once a deployment says which names are its own."""

    def test_a_named_host_is_served(self):
        client, _ = build(["links.example"])

        assert client.get("/page", headers={"Host": "links.example"}).status_code == 200

    def test_another_name_is_refused(self):
        client, _ = build(["links.example"])

        assert client.get("/page", headers={"Host": "evil.example"}).status_code == 400

    def test_the_refusal_is_recorded(self):
        """An operator who set the list wrongly has to be able to see it."""
        client, logger = build(["links.example"])

        client.get("/page", headers={"Host": "evil.example"})

        assert len(logger.warnings) == 1
        assert logger.warnings[0][1]["requested_host"] == "evil.example"

    def test_the_offending_name_is_not_in_the_body(self):
        """It is attacker-chosen text; the journal is where it belongs."""
        client, _ = build(["links.example"])

        answer = client.get("/page", headers={"Host": "evil.example"})

        assert b"evil.example" not in answer.data


class TestThePortIsNotPartOfTheName:
    """Why the comparison drops it."""

    def test_a_named_host_reached_on_another_port_is_served(self):
        """The stack's own health check asks ``localhost:${PORT}``.

        A list that had to name the port would break the moment somebody
        moved the port, and the health check would fail with the service
        working perfectly.
        """
        client, _ = build(["localhost"])

        assert client.get("/page", headers={"Host": "localhost:5000"}).status_code == 200

    def test_a_port_written_into_the_list_is_ignored(self):
        """An operator who pastes ``example.com:443`` is not punished."""
        client, _ = build(["links.example:443"])

        assert client.get("/page", headers={"Host": "links.example"}).status_code == 200


class TestSpellingsOfOneName:
    """What ``normalise_host`` folds together."""

    @pytest.mark.parametrize(
        "value, expected",
        [
            ("Example.COM", "example.com"),
            ("example.com.", "example.com"),
            ("example.com:8080", "example.com"),
            ("https://example.com/path", "example.com"),
            ("  example.com  ", "example.com"),
            ("[::1]:5000", "::1"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_it_reduces_to_the_bare_name(self, value, expected):
        assert normalise_host(value) == expected

    def test_a_malformed_authority_is_a_name_we_do_not_have(self):
        """An unclosed bracket must be a refusal, not a 500."""
        assert normalise_host("[::1") == ""

    def test_case_does_not_open_the_door(self):
        client, _ = build(["links.example"])

        assert client.get("/page", headers={"Host": "LINKS.EXAMPLE"}).status_code == 200

    def test_a_blank_entry_does_not_admit_a_blank_host(self):
        """An empty string in the list must not become a wildcard."""
        client, _ = build(["links.example", "  "])

        assert client.get("/page", headers={"Host": "evil.example"}).status_code == 400


class TestNoWildcards:
    """The suffix match that is deliberately not implemented."""

    def test_a_leading_dot_matches_nothing_but_itself(self):
        """``.example.com`` is how ``evilexample.com`` gets let in elsewhere.

        A service on one domain has nothing to spend that risk on, so the
        entry is read as an ordinary (and unmatchable) name rather than as
        a pattern.
        """
        client, _ = build([".example.com"])

        assert client.get("/page", headers={"Host": "sub.example.com"}).status_code == 400
        assert client.get("/page", headers={"Host": "evilexample.com"}).status_code == 400
