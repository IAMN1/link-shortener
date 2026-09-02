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
        assert OriginalUrl("http://127.0.0.1.nip.io/x").normalize() == (
            "http://127.0.0.1.nip.io/x"
        )


class TestAHostWrittenAsAnAddressThatDoesNotAddUp:
    """
    Refusals the parser reaches on its way to deciding what an address is.

    Each of these lines was reachable and unreached: the ``999.1.1.1``
    check above stops at the first of them, and the rest -- too many
    parts, a part that is not a number, a last part with more in it than
    the octets it has to fill -- were held by nothing. Measured: flipping
    the comparison that bounds the last part left the whole suite green.
    """

    def test_more_parts_than_an_address_has(self):
        with pytest.raises(ValidationError, match="Invalid IP address"):
            OriginalUrl("http://1.2.3.4.5/x")

    def test_a_part_that_is_not_a_number_at_all(self):
        """The last part is a number, so this host is read as an address;
        a part before it that is not one makes it a broken one rather than
        a name."""
        with pytest.raises(ValidationError, match="Invalid IP address"):
            OriginalUrl("http://8.8.zz.8/x")

    def test_the_last_octet_at_its_ceiling_is_an_address(self):
        """255 is the largest an octet holds, and it is inside."""
        assert OriginalUrl("http://8.8.8.255/x").normalize() == (
            "http://8.8.8.255/x"
        )

    def test_one_past_the_last_octet_is_not(self):
        with pytest.raises(ValidationError, match="Invalid IP address"):
            OriginalUrl("http://8.8.8.256/x")

    def test_a_short_form_fills_the_octets_it_left_out(self):
        """Three parts, so the last one fills two octets and may hold up
        to 65535. The number here is far past one octet and well inside
        two, which is the whole of what this arithmetic is for."""
        assert OriginalUrl("http://8.8.2048/x").normalize() == (
            "http://8.8.2048/x"
        )

    def test_one_past_what_the_short_form_can_hold_is_refused(self):
        with pytest.raises(ValidationError, match="Invalid IP address"):
            OriginalUrl("http://8.8.65536/x")

    def test_a_bare_radix_prefix_counts_as_zero(self):
        """``0x`` with no digits is 0 to ``inet_aton``, so this host is
        ``0.8.8.8`` -- inside ``0.0.0.0/8``, which is not a public
        destination. Read as a name instead, it would be admitted."""
        with pytest.raises(ValidationError, match="public address"):
            OriginalUrl("http://0x.8.8.8/x")


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


class TestAHostWithATrailingDot:
    """
    The root form of a name, admitted and reduced to the name it spells.

    ``example.com.`` is the fully qualified spelling of ``example.com``:
    the last label is the root, every resolver accepts it and so does
    every browser. It used to be refused, and refused for the wrong
    reason -- ``_validate_host`` split on the dots, found an empty last
    label and said ``Empty label in host`` -- which also left the
    trailing-dot handling in ``_as_ip_address`` and
    ``_validate_public_target`` unreachable from outside.

    The root label is dropped in two places now: at the top of
    ``_validate_host``, so the name is admitted, and in
    ``_to_ascii_host``, which is what ``_validate_public_target`` reads
    the address out of and what ``normalize`` builds the stored form
    from. The second is the load-bearing one. Left off, ``127.0.0.1.``
    ends in an empty label, the address reader calls the host a name, and
    the internal-address check never looks at it -- the trailing dot would
    open the loopback, in one line, in a different file.
    """

    def test_the_dot_is_dropped_and_the_host_is_still_an_address(self):
        assert str(OriginalUrl._as_ip_address("127.0.0.1.")) == "127.0.0.1"

    def test_a_public_address_reads_the_same_way(self):
        assert str(OriginalUrl._as_ip_address("8.8.8.8.")) == "8.8.8.8"

    def test_a_name_with_a_trailing_dot_is_still_a_name(self):
        """Only the dot is dropped; what is in front of it still decides."""
        assert OriginalUrl._as_ip_address("example.com.") is None

    def test_the_root_form_of_a_public_name_is_admitted(self):
        assert OriginalUrl("http://example.com./x").normalize() == (
            "http://example.com/x"
        )

    def test_it_deduplicates_onto_the_name_without_the_dot(self):
        """One destination, one hash, one short code. Normalised apart,
        the two spellings would be two links pointing at one place."""
        assert (
            OriginalUrl("http://example.com./x").normalize()
            == OriginalUrl("http://example.com/x").normalize()
        )

    def test_an_international_name_survives_its_root_label(self):
        """``idna.encode`` refuses a name ending in a dot, so the root
        label had to come off before the punycode form is built."""
        assert OriginalUrl("http://\u043f\u0440\u0438\u043c\u0435\u0440.\u0440\u0444./").normalize() == (
            "http://xn--e1afmkfd.xn--p1ai/"
        )

    @pytest.mark.parametrize("url", [
        "http://127.0.0.1./x",
        "http://0177.0.0.1./x",
        "http://127.1./x",
        "http://169.254.169.254./x",
        "http://10.0.0.1./x",
        "http://localhost./x",
        "http://kubernetes.default.svc./x",
        "http://metadata.google.internal./x",
    ])
    def test_the_root_label_does_not_reopen_an_internal_target(self, url):
        """The whole risk of admitting the dot, pinned: every one of these
        was refused before and has to stay refused."""
        with pytest.raises(ValidationError, match="public address"):
            OriginalUrl(url)

    def test_two_dots_are_still_an_empty_label(self):
        """Exactly one root label is dropped. The second dot is a label
        with nothing in it, and that is the refusal this used to give
        every fully qualified name."""
        with pytest.raises(ValidationError, match="Empty label"):
            OriginalUrl("http://example.com../x")


class TestWhatTheAddressReaderRefusesOnItsOwn:
    """
    Two more guards behind the parser, asked of the reader directly.

    A bracketed authority is checked before this runs and a bare one with
    colons in it is refused as a bad port, so no URL arrives here with an
    IPv6 host in it. What the reader does when one does is still worth
    pinning: it is the difference between a refusal and a host silently
    read as a name.
    """

    def test_something_bracket_free_with_colons_that_is_not_an_address(self):
        with pytest.raises(ValidationError, match="Invalid IP address"):
            OriginalUrl._as_ip_address("::zz")

    def test_an_ipv6_address_without_brackets_is_read_as_one(self):
        assert str(OriginalUrl._as_ip_address("::1")) == "::1"

    def test_an_empty_part_is_not_a_number(self):
        """Which is what makes an empty last label read as a name rather
        than as the zero it would otherwise parse to."""
        assert OriginalUrl._parse_ipv4_part("") is None


class TestAUrlWithAPortAndNoHost:

    def test_it_says_the_hostname_is_missing(self):
        with pytest.raises(ValidationError, match="must have a hostname"):
            OriginalUrl("https://:80/x")
