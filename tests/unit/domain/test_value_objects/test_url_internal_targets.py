"""
Tests that a short link cannot be aimed inside the deployment's network.

A shortener is a request forwarder: whoever creates the link chooses the
destination, and whoever opens it makes the request. Left open, an
anonymous caller could shorten ``http://169.254.169.254/latest/meta-data/``
and hand out a link that reads cloud instance metadata from inside the
victim's network, under this service's domain -- and the same for a loopback
admin interface or any private subnet.

Two things had to be true for the block to mean anything:

- it is applied to the address a resolver would use, not to the spelling
  submitted. ``0177.0.0.1``, ``0x7f.0.0.1`` and ``127.1`` are all the
  loopback to ``inet_aton`` and to every browser, while none of them is an
  address to ``ipaddress.ip_address``;
- credentials are refused outright. Everything before ``@`` is opaque to
  this validator and not to the browser, which reads ``\\`` as a separator:
  ``http://evil.example\\@public.example/`` is ``public.example`` to
  ``urlparse`` and ``evil.example`` to whoever follows the redirect.
"""

import pytest

from link_shortener.domain import OriginalUrl, ValidationError


PUBLIC = "https://target.example.com/page"


class TestInternalAddressesAreRefused:
    """The four the audit reproduced, and the families they belong to."""

    @pytest.mark.parametrize(
        "url",
        [
            "http://169.254.169.254/latest/meta-data/",  # cloud metadata
            "http://127.0.0.1:5000/admin",               # loopback
            "http://[::1]/x",                            # loopback, IPv6
            "http://10.0.0.1/x",                         # private network
            "http://192.168.1.1/x",
            "http://172.16.0.1/x",
            "http://100.64.0.1/x",                       # carrier-grade NAT
            "http://0.0.0.0/x",                          # unspecified
            "http://255.255.255.255/x",                  # broadcast
            "http://224.0.0.1/x",                        # multicast
            "http://240.0.0.1/x",                        # reserved
            "http://[fe80::1]/x",                        # link-local, IPv6
            "http://[fc00::1]/x",                        # unique local
            "http://[::]/x",
        ],
    )
    def test_the_address_is_not_admitted(self, url):
        with pytest.raises(ValidationError, match="public address"):
            OriginalUrl(url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://[::ffff:127.0.0.1]/x",   # IPv4-mapped
            "http://[::ffff:10.0.0.1]/x",
            "http://[2002:7f00:1::]/x",      # 6to4 carrying 127.0.0.1
            "http://[2001:0:0:0:0:0:7f00:1]/x",  # Teredo carrying 127.0.0.1
        ],
    )
    def test_an_ipv4_address_embedded_in_ipv6_is_not_a_way_round(self, url):
        """The v6 wrapper is public-looking; the address it carries is not."""
        with pytest.raises(ValidationError, match="public address"):
            OriginalUrl(url)


class TestObfuscatedSpellingsOfTheLoopback:
    """
    Every one of these reaches 127.0.0.1 from a browser.

    None of them is an IP address to ``ipaddress.ip_address``, which is why
    a blocklist keyed on the strict spelling is not a blocklist at all.
    """

    @pytest.mark.parametrize(
        "host",
        [
            "127.1",            # two parts, the last one filling three octets
            "127.0.1",          # three parts
            "0177.0.0.1",       # octal
            "0x7f.0.0.1",       # hexadecimal
            "0x7f000001",       # one hexadecimal number
            "017700000001",     # one octal number
            "127.0.0.01",
        ],
    )
    def test_the_loopback_is_refused_however_it_is_written(self, host):
        with pytest.raises(ValidationError):
            OriginalUrl(f"http://{host}/x")

    @pytest.mark.parametrize(
        "host",
        [
            "１２７．０．０．１",      # fullwidth digits, fullwidth stops
            "127。0。0。1",        # ideographic stops
            "127．0．0．1",        # ASCII digits, fullwidth stops
            "127｡0｡0｡1",         # halfwidth ideographic stops
            "１２７.1",            # fullwidth digits, ASCII stop, short form
            "０ｘ７f．０．０．１",    # fullwidth hexadecimal
        ],
    )
    def test_a_national_spelling_of_the_octets_is_still_the_loopback(self, host):
        """
        UTS-46 maps every one of these to ``127.0.0.1`` -- which is what a
        browser does before connecting, and what this object's own
        ``normalize()`` did while the check still read the raw spelling.
        """
        with pytest.raises(ValidationError, match="public address"):
            OriginalUrl(f"http://{host}/x")

    def test_the_metadata_address_cannot_be_smuggled_that_way_either(self):
        with pytest.raises(ValidationError, match="public address"):
            OriginalUrl("http://169。254。169。254/latest/meta-data/")

    def test_a_host_written_as_an_address_that_is_not_one_is_refused(self):
        """A browser refuses it too, so admitting it stores an unopenable link."""
        with pytest.raises(ValidationError, match="Invalid IP address"):
            OriginalUrl("http://999.1.1.1/x")

    def test_a_name_that_merely_contains_digits_is_still_a_name(self):
        assert OriginalUrl("http://127.0.0.1.nip.io/x").get_domain() == (
            "127.0.0.1.nip.io"
        )


class TestNamesReservedForLocalUse:
    """RFC 6761/6762/8375 names, plus the ICANN reservation of ``.internal``."""

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost/x",
            "http://LOCALHOST/x",
            "http://api.localhost/x",
            "http://printer.local/x",
            "http://metadata.google.internal/x",
            "http://gw.home.arpa/x",
            "http://kubernetes.default.svc/x",   # the cluster's API server
            "http://consul.service.consul/x",
            "http://box.localdomain/x",
            "http://wiki.corp/x",
            "http://nas.lan/x",
            "http://portal.intranet/x",
            "http://vm.novalocal/x",
            "http://x.private/x",
            "http://x.home/x",
            "http://x.mail/x",
            "http://x.alt/x",
        ],
    )
    def test_the_name_is_not_admitted(self, url):
        with pytest.raises(ValidationError, match="public address"):
            OriginalUrl(url)

    def test_a_public_name_ending_in_the_same_letters_is_admitted(self):
        """``notlocalhost.example.com`` is not under ``localhost``."""
        assert OriginalUrl("http://notlocalhost.example.com/x")


class TestCredentialsAreRefused:
    """
    Userinfo shows the victim one host and takes them to another.

    It also puts a stretch of the authority beyond the reach of every host
    check below it, which is the reason this is refused rather than ignored.
    """

    def test_a_url_with_credentials_is_not_admitted(self):
        with pytest.raises(ValidationError, match="credentials"):
            OriginalUrl("http://user:pass@evil.example/x")

    def test_a_bare_username_is_enough_to_be_refused(self):
        with pytest.raises(ValidationError, match="credentials"):
            OriginalUrl("http://www.paypal.com@evil.example/x")

    def test_the_backslash_disguise_is_refused(self):
        """
        ``urlparse`` reads the host as ``public.example``; a browser reads
        ``\\`` as a separator and goes to ``evil.example``.
        """
        with pytest.raises(ValidationError, match="credentials"):
            OriginalUrl("http://evil.example\\@public.example/x")

    def test_an_at_sign_in_the_path_is_not_credentials(self):
        assert OriginalUrl("https://target.example.com/u@host")


class TestPublicDestinationsStillPass:
    """The ban must not cost the service its actual purpose."""

    @pytest.mark.parametrize(
        "url",
        [
            PUBLIC,
            "http://8.8.8.8/x",
            "http://[2606:4700:4700::1111]/x",
            "https://sub.domain.example.com/path?q=1",
        ],
    )
    def test_an_ordinary_destination_is_admitted(self, url):
        assert OriginalUrl(url).value == url


class TestStoredRowsStayReadable:
    """
    The ban is an admission rule: it decides what may enter, not what may
    be read back.

    Rows written before it existed point at internal addresses. If reading
    them raised, one such row would fail every maintenance sweep -- the very
    sweep that would delete it.
    """

    @pytest.mark.parametrize(
        "stored",
        [
            "http://127.0.0.1:5000/admin",
            "http://169.254.169.254/latest/meta-data/",
            "http://user:pass@evil.example/x",
            "http://localhost/x",
        ],
    )
    def test_a_row_written_before_the_ban_can_still_be_read(self, stored):
        assert OriginalUrl.from_storage(stored).value == stored

    def test_reading_still_refuses_something_that_is_not_a_url(self):
        with pytest.raises(ValidationError):
            OriginalUrl.from_storage("nonsense")


class TestTheOperatorCanOptOut:
    """
    An intranet-only deployment shortening intranet links is a real use, and
    ``ALLOW_INTERNAL_TARGETS`` is how it says so. Off unless said.
    """

    def test_internal_targets_are_admitted_when_allowed(self):
        url = OriginalUrl("http://10.0.0.1/x", allow_internal_targets=True)

        assert url.value == "http://10.0.0.1/x"

    def test_credentials_are_still_refused_when_internal_is_allowed(self):
        """A different rule, for a different reason: it is not part of the knob."""
        with pytest.raises(ValidationError, match="credentials"):
            OriginalUrl("http://u:p@10.0.0.1/x", allow_internal_targets=True)

    def test_the_default_blocks(self):
        with pytest.raises(ValidationError, match="public address"):
            OriginalUrl("http://10.0.0.1/x")
