"""
Tests for which address the service believes a request came from.

``X-Forwarded-For`` is a list a proxy appends to. Nginx's
``$proxy_add_x_forwarded_for`` writes whatever the client sent and then the
address it actually saw, so the rightmost entry is the only one the client
could not choose. Reading the leftmost -- which is what this did -- let the
caller declare their own identity, and the address is not cosmetic: it is
the guest quota's counter and the ``guest_identifier`` column.

Two consequences, both reachable as soon as ``TRUSTED_PROXIES`` is filled
in, which ``.env.example`` advises for any deployment behind a proxy:

- a fresh value on every request, and the guest quota counts nothing;
- a victim's address, and the attacker's links are charged to the victim's
  allowance, locking them out for the window.
"""

import pytest
from flask import Flask

from link_shortener.web.security.context import get_client_ip


PROXY = "10.0.0.9"
REAL_CLIENT = "198.51.100.7"


@pytest.fixture
def app():
    """A bare app: this function reads only the config and the request."""
    application = Flask(__name__)
    application.config["TRUSTED_PROXIES"] = [PROXY]
    return application


def _ip(app, remote_addr, forwarded_for=None):
    """Ask what the client address is for one made-up request."""
    headers = {"X-Forwarded-For": forwarded_for} if forwarded_for else {}
    with app.test_request_context(
        "/", headers=headers, environ_base={"REMOTE_ADDR": remote_addr}
    ):
        return get_client_ip()


class TestBehindATrustedProxy:
    """The header is read, and read from the right end."""

    def test_the_entry_the_proxy_appended_is_taken(self, app):
        assert _ip(app, PROXY, f"1.2.3.4, {REAL_CLIENT}") == REAL_CLIENT

    def test_a_value_the_client_invented_is_not_taken(self, app):
        """The client controls everything left of the proxy's own entry."""
        assert _ip(app, PROXY, f"9.9.9.9, 8.8.8.8, {REAL_CLIENT}") == REAL_CLIENT

    def test_a_single_entry_is_taken(self, app):
        assert _ip(app, PROXY, REAL_CLIENT) == REAL_CLIENT

    def test_surrounding_whitespace_is_ignored(self, app):
        assert _ip(app, PROXY, f"1.2.3.4 ,  {REAL_CLIENT}  ") == REAL_CLIENT

    def test_an_ipv6_entry_is_taken_in_canonical_form(self, app):
        """Two spellings of one address must not count as two guests."""
        assert _ip(app, PROXY, "2001:0db8:0000::0001") == "2001:db8::1"

    def test_a_bracketed_ipv6_entry_is_taken(self, app):
        assert _ip(app, PROXY, "[2001:db8::1]") == "2001:db8::1"


class TestAnEntryThatIsNotAnAddress:
    """
    ``guest_identifier`` is a ``VARCHAR(45)``: an arbitrary header used to
    reach the insert and fail it on PostgreSQL. The connection's own address
    is the truthful answer whenever the header is not usable.
    """

    @pytest.mark.parametrize(
        "forwarded_for",
        [
            "not-an-address",
            "x" * 200,
            "1.2.3.4, ",
            "999.999.999.999",
            "127.0.0.1:8080",
            "<script>alert(1)</script>",
        ],
    )
    def test_the_connection_address_is_used_instead(self, app, forwarded_for):
        assert _ip(app, PROXY, forwarded_for) == PROXY

    @pytest.mark.parametrize(
        "forwarded_for",
        [
            "fe80::1%eth0",
            "fe80::1%" + "x" * 120,
            "[fe80::1%eth0]",
            "2001:db8::1%1",
        ],
    )
    def test_an_address_with_a_scope_identifier_is_not_an_identity(
        self, app, forwarded_for
    ):
        """
        ``ipaddress.ip_address`` takes any text after "%" as a scope, and a
        scope names an interface on the machine reading it -- nothing about
        a caller two hops away. Accepted, it made the guest identity both
        free to invent (``%eth0``, ``%eth1``, ... are one address and many
        guests, so the quota counts nothing) and unbounded in length, which
        overran ``guest_identifier`` and failed the insert on PostgreSQL.
        """
        assert _ip(app, PROXY, forwarded_for) == PROXY

    def test_whatever_is_returned_fits_the_column(self, app):
        """``urls.guest_identifier`` is a VARCHAR(45)."""
        longest = _ip(app, PROXY, "::ffff:255.255.255.255")

        assert len(longest) <= 45


class TestWithoutATrustedProxy:
    """An untrusted peer's header is not evidence of anything."""

    def test_the_header_is_ignored(self, app):
        assert _ip(app, "203.0.113.5", REAL_CLIENT) == "203.0.113.5"

    def test_the_connection_address_is_used_when_there_is_no_header(self, app):
        assert _ip(app, "203.0.113.5") == "203.0.113.5"

    def test_an_absent_address_yields_an_empty_string(self, app):
        with app.test_request_context("/", environ_base={"REMOTE_ADDR": None}):
            assert get_client_ip() == ""
