"""
Tests for how a host is read: national scripts, ports, and configured limits.

Three findings meet in ``OriginalUrl``'s host handling:

- an international name was refused outright, because the label regex knows
  only ASCII and never saw the punycode form that actually travels over DNS;
- the default port was cut out of the authority as a substring, so
  ``http://[2606:4700::80:1]:80/`` normalized to ``http://[2606:4700::1]/``
  -- a different host, hence the same hash and the same short code as one.
  Within a deduplication scope, and every anonymous caller behind one
  address shares one, that hands the second caller a link pointing where
  they never asked;
- ``MAX_URL_LENGTH`` existed in the configuration while the value object
  had 2048 written into it.
"""

import pytest

from link_shortener.domain import OriginalUrl, ValidationError


class TestInternationalNames:
    """Accepted as submitted, compared in the form DNS uses."""

    def test_an_idn_url_is_admitted(self):
        url = OriginalUrl("https://пример.рф/тест")

        assert url.value == "https://пример.рф/тест"

    def test_both_spellings_of_one_name_deduplicate_together(self):
        """Otherwise one name yields two links and two short codes."""
        unicode_form = OriginalUrl("https://пример.рф/тест").normalize()
        punycode_form = OriginalUrl(
            "https://xn--e1afmkfd.xn--p1ai/тест"
        ).normalize()

        # Pinned to the punycode literal, not merely to each other: two
        # calls collapsing onto the same wrong answer would satisfy an
        # equality between them and prove nothing.
        assert unicode_form == "https://xn--e1afmkfd.xn--p1ai/тест"
        assert punycode_form == unicode_form

    def test_case_folding_is_part_of_it(self):
        assert OriginalUrl("https://ПРИМЕР.рф/").normalize() == (
            "https://xn--e1afmkfd.xn--p1ai/"
        )

    def test_a_name_that_is_not_expressible_in_punycode_is_refused(self):
        with pytest.raises(ValidationError):
            OriginalUrl("https://.example/")

    def test_a_national_path_survives_untouched(self):
        """Only the host is transliterated; the rest is the caller's."""
        assert OriginalUrl("https://пример.рф/тест").normalize().endswith("/тест")


class TestDefaultPortNormalization:
    """RFC 3986 §6.2.3 -- the two forms are one resource."""

    @pytest.mark.parametrize(
        "with_port,without_port",
        [
            ("http://example.com:80/x", "http://example.com/x"),
            ("https://example.com:443/x", "https://example.com/x"),
        ],
    )
    def test_the_default_port_is_dropped(self, with_port, without_port):
        # Compared against the parametrised literal rather than against
        # `OriginalUrl(without_port).normalize()`: normalisation collapsing
        # every input onto one string would keep that equality true.
        assert OriginalUrl(with_port).normalize() == without_port

    def test_a_non_default_port_is_kept(self):
        assert OriginalUrl("http://example.com:8080/x").normalize() == (
            "http://example.com:8080/x"
        )

    def test_the_port_of_one_scheme_is_not_the_default_of_another(self):
        assert OriginalUrl("https://example.com:80/x").normalize() == (
            "https://example.com:80/x"
        )

    def test_an_ipv6_group_that_reads_as_a_port_is_not_a_port(self):
        """
        The whole finding in one line: cutting ``':80'`` out of the authority
        reached into the address itself.
        """
        collided = OriginalUrl("http://[2606:4700::80:1]:80/x").normalize()

        assert collided == "http://[2606:4700::80:1]/x"
        assert collided != OriginalUrl("http://[2606:4700::1]/x").normalize()

    def test_two_different_ipv6_hosts_keep_two_codes(self):
        first = OriginalUrl("http://[2606:4700::80:1]:80/x").normalize()
        second = OriginalUrl("http://[2606:4700::1]:80/x").normalize()

        assert first != second


class TestConfiguredLimits:
    """The value object takes its limits from the caller, not from itself."""

    def test_the_length_limit_is_the_one_passed_in(self):
        long_url = "https://example.com/" + "a" * 100

        with pytest.raises(ValidationError, match="max 50 characters"):
            OriginalUrl(long_url, max_length=50)

    def test_the_same_url_passes_under_a_wider_limit(self):
        long_url = "https://example.com/" + "a" * 100

        assert OriginalUrl(long_url, max_length=2048).value == long_url

    def test_a_url_of_exactly_the_limit_is_admitted(self):
        """The limit is a ceiling, not a bar one short of it.

        Written as ``>``, so the only URL that tells the two spellings
        apart is the one of exactly this length: a limit compared with
        ``>=`` refuses a URL the setting says it accepts, and every other
        test in this class stays green.
        """
        exact = "https://example.com/" + "a" * (50 - len("https://example.com/"))
        assert len(exact) == 50

        assert OriginalUrl(exact, max_length=50).value == exact

    def test_one_character_past_the_limit_is_refused(self):
        one_more = "https://example.com/" + "a" * (
            51 - len("https://example.com/")
        )
        assert len(one_more) == 51

        with pytest.raises(ValidationError, match="max 50 characters"):
            OriginalUrl(one_more, max_length=50)

    def test_the_limits_are_settings_and_not_part_of_the_value(self):
        """Two objects over the same URL are the same URL.

        The limits are carried on the value object as fields, and a field
        counts towards equality unless it says otherwise. Counting them
        would make one URL unequal to itself across a settings change --
        and this object is a dictionary key in the deduplication path,
        where that means two links for one address.
        """
        url = "https://example.com/a-page"

        assert OriginalUrl(url, max_length=2048) == OriginalUrl(url, max_length=64)
        assert len({OriginalUrl(url, max_length=2048),
                    OriginalUrl(url, max_length=64)}) == 1

    def test_a_row_longer_than_the_current_limit_can_still_be_read(self):
        """
        The limit is a setting an operator can narrow, so it is an admission
        rule. Narrowing it must not make already stored rows unreadable.
        """
        stored = "https://example.com/" + "a" * 3000

        assert OriginalUrl.from_storage(stored).value == stored


class TestBracketsMeanAnAddress:
    """
    ``[v1.example.com]`` is RFC 3986's IPvFuture form, and nothing
    dereferences it: ``new URL()`` refuses it, curl answers "bad range in
    URL". ``urlparse`` accepts it and strips the brackets, which made it a
    second spelling of an ordinary name -- and deduplication is keyed on
    the normalized form.
    """

    @pytest.mark.parametrize(
        "url",
        [
            "http://[v1.good.example]/",
            "http://[v2.api.example.com]/x",
            "http://[vFF.good.example]:8080/a?b",
        ],
    )
    def test_a_bracketed_name_is_refused(self, url):
        with pytest.raises(ValidationError, match="IPv6"):
            OriginalUrl(url)

    def test_a_bracketed_name_with_no_version_never_reaches_that_check(self):
        """Refused one step earlier, and so with the other message.

        ``[example.com]`` is not even IPvFuture -- no ``v<hex>.`` prefix --
        so ``urlparse`` raises on it instead of handing back a host for
        ``_validate_bracketed_host_is_an_address`` to judge. The message
        is the one ``_parse`` produces, which names the authority rather
        than quoting it: the quoted form carries a password into the log
        when the authority holds one.
        """
        with pytest.raises(ValidationError, match="authority cannot be parsed"):
            OriginalUrl("http://[example.com]/")

    def test_a_bracketed_ipv6_address_is_still_admitted(self):
        assert OriginalUrl("http://[2606:4700::1]/x")

    def test_a_row_written_before_the_check_does_not_steal_a_name(self):
        """
        Read back rather than refused, and not sharing a hash with the
        name it wraps: sharing one hands a caller shortening the real URL
        the code of a link no browser can open, and no working one while
        that row lives.
        """
        stored = OriginalUrl.from_storage("http://[v1.good.example]/")
        plain = OriginalUrl("http://v1.good.example/")

        assert stored.normalize() != plain.normalize()
        assert stored.normalize() == "http://[v1.good.example]/"


class TestAUrlThatCannotBeSplitAtAll:
    """
    ``urlparse`` raises plain ``ValueError`` for these, and a ``ValueError``
    out of a value object belongs to nobody: the handler for
    ``ValidationError`` does not see it, and on the redirect path it reached
    the catch-all as a 500.
    """

    @pytest.mark.parametrize(
        "url",
        [
            "http://good.example\u2100evil.example/",  # NFKC check in _checknetloc
            "http://good.example\uff0fevil.example/",
            "http://[]/",
            "http://[v1/",
            "http://[vz.x]/",
        ],
    )
    def test_it_is_a_validation_error_and_not_a_value_error(self, url):
        with pytest.raises(ValidationError):
            OriginalUrl(url)

    def test_reading_such_a_row_back_is_also_a_validation_error(self):
        with pytest.raises(ValidationError):
            OriginalUrl.from_storage("http://[v1/")


class TestTheLimitsDnsImposes:
    """253 bytes for the whole name, 63 for one label -- RFC 1035.

    Both are written as ``>``, and a name of exactly the limit is the only
    one that tells that from ``>=``. Without these, a host the resolver
    accepts could be refused here and nothing in the suite would say so.
    """

    def test_a_host_of_exactly_the_longest_name_is_admitted(self):
        # Four labels of 63 and one of 61, plus the four dots: 253.
        host = ".".join(["a" * 63] * 3 + ["b" * 61])
        assert len(host) == 253

        assert OriginalUrl(f"https://{host}/x").value == f"https://{host}/x"

    def test_one_byte_past_the_longest_name_is_refused(self):
        host = ".".join(["a" * 63] * 3 + ["b" * 62])
        assert len(host) == 254

        with pytest.raises(ValidationError, match="Host too long"):
            OriginalUrl(f"https://{host}/x")

    def test_a_label_of_exactly_the_longest_label_is_admitted(self):
        host = f"{'a' * 63}.example.com"

        assert OriginalUrl(f"https://{host}/x").value == f"https://{host}/x"

    def test_one_byte_past_the_longest_label_is_refused(self):
        host = f"{'a' * 64}.example.com"

        with pytest.raises(ValidationError, match="Label too long"):
            OriginalUrl(f"https://{host}/x")
