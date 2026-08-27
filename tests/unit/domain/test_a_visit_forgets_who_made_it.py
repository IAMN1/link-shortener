"""
Tests the reduction a visit goes through before it is stored.

The rule this file defends is one sentence: no row ever holds a full
address or a User-Agent string. Everything else here -- which network,
which device class -- is a detail of how much is kept. The rule is what
makes the table safe to keep for ninety days, and it is only a rule
while something checks it.
"""

import pytest

from link_shortener.domain import LinkVisit, anonymise_address, classify_client


class TestAnAddressIsReducedToItsNetwork:

    @pytest.mark.parametrize("address,network", [
        ("203.0.113.42", "203.0.113.0"),
        ("203.0.113.255", "203.0.113.0"),
        ("10.0.0.1", "10.0.0.0"),
        # IPv6 keeps the /64 a provider hands out as one allocation, and
        # nothing below it.
        ("2001:db8:1:2:3:4:5:6", "2001:db8:1:2::"),
        ("::1", "::"),
    ])
    def test_the_host_part_is_gone(self, address, network):
        assert anonymise_address(address) == network

    def test_two_hosts_on_one_network_become_the_same_value(self):
        """
        Which is the point: a chart can count networks, not people.
        """
        assert anonymise_address("198.51.100.7") == anonymise_address("198.51.100.200")

    @pytest.mark.parametrize("address,network", [
        ("::ffff:203.0.113.5", "203.0.113.0"),
        ("::ffff:198.51.100.200", "198.51.100.0"),
        # The same address written the long way: a dual-stack socket may
        # hand over either spelling.
        ("::ffff:cb00:7105", "203.0.113.0"),
    ])
    def test_an_ipv4_address_behind_a_dual_stack_listener_keeps_its_network(
        self, address, network
    ):
        """
        A socket bound to `::` reports every IPv4 client in this form.

        Read as an IPv6 address it loses everything below the /64, and the
        /64 of an IPv4-mapped address is `::` for all of them -- so with
        `HOST=::`, or nginx passing `ipv6only=off`, every IPv4 visitor in
        the world was recorded as one network and the chart had a single
        bar where the traffic was.
        """
        assert anonymise_address(address) == network

    def test_two_dual_stack_clients_stay_two_networks(self):
        assert anonymise_address("::ffff:203.0.113.5") != anonymise_address(
            "::ffff:198.51.100.7"
        )

    @pytest.mark.parametrize("junk", [
        None, "", "   ", "not-an-address", "999.1.1.1", "1.2.3", "<script>",
    ])
    def test_what_does_not_parse_is_dropped_rather_than_stored(self, junk):
        """
        The value arrives from a proxy header, so it is whatever anyone put
        there. Storing it unparsed would put a caller's text in a column
        the charts group by.
        """
        assert anonymise_address(junk) is None


class TestAUserAgentIsReducedToThreeFacts:

    @pytest.mark.parametrize("user_agent,device,browser", [
        ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/120.0 Safari/537.36", "desktop", "chrome"),
        ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
         "AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1", "mobile", "safari"),
        ("Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
         "Safari/604.1", "tablet", "safari"),
        ("Mozilla/5.0 (Windows NT 10.0) Gecko/20100101 Firefox/121.0",
         "desktop", "firefox"),
        ("Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/120.0 "
         "Safari/537.36 Edg/120.0", "desktop", "edge"),
    ])
    def test_the_family_and_the_screen(self, user_agent, device, browser):
        assert classify_client(user_agent) == (device, browser, False)

    @pytest.mark.parametrize("user_agent,device", [
        # Every iPadOS string carries `Mobile/15E148`, and has since iPadOS
        # 13 started asking for desktop pages by default. Tried after the
        # phone rule, `ipad` is unreachable: the token that makes a tablet
        # a tablet arrives in the same string as the token that makes a
        # phone a phone.
        ("Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
         "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
         "tablet"),
        # The phone the same rule has to keep answering for.
        ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
         "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
         "Mobile/15E148 Safari/604.1", "mobile"),
        # Android says it the other way round: a tablet is the string with
        # no `Mobile` in it, so the phone must not be read as one.
        ("Mozilla/5.0 (Linux; Android 13; SM-X200) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", "tablet"),
        ("Mozilla/5.0 (Linux; Android 13; SM-A536B) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
         "mobile"),
        # Firefox names the class outright, and names it in both.
        ("Mozilla/5.0 (Android 13; Tablet; rv:121.0) Gecko/121.0 "
         "Firefox/121.0", "tablet"),
        ("Mozilla/5.0 (Android 13; Mobile; rv:121.0) Gecko/121.0 "
         "Firefox/121.0", "mobile"),
    ])
    def test_a_tablet_is_not_counted_as_a_phone(self, user_agent, device):
        """
        Written from strings the devices actually send.

        The case above this one used an iPad string with no `Mobile` token,
        which no iPad has sent since 2019 -- so it passed while every real
        iPad was being recorded as a phone, and the chart's tablet column
        counted only the Android half of them.
        """
        assert classify_client(user_agent)[0] == device

    def test_edge_is_not_reported_as_chrome(self):
        """
        Every Chromium browser carries "Chrome" in its string, so the order
        the patterns are tried in is load-bearing rather than cosmetic.
        """
        _, browser, _ = classify_client(
            "Mozilla/5.0 AppleWebKit/537.36 Chrome/120 Safari/537.36 Edg/120"
        )
        assert browser == "edge"

    @pytest.mark.parametrize("user_agent", [
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "facebookexternalhit/1.1",
        "TelegramBot (like TwitterBot)",
        "Slackbot-LinkExpanding 1.0",
        "curl/8.4.0",
        "python-requests/2.31.0",
        "Mozilla/5.0 HeadlessChrome/120.0",
    ])
    def test_a_robot_is_marked_as_one(self, user_agent):
        """
        A link posted to a chat is fetched by that chat's preview fetcher
        within seconds. Counted as a reader, it is a visit nobody made.
        """
        device, browser, is_bot = classify_client(user_agent)

        assert is_bot is True
        assert browser == "bot"
        # A crawler's device is whatever its operator chose to imitate.
        assert device == "unknown"

    def test_a_missing_header_is_not_an_error(self):
        assert classify_client(None) == ("unknown", "unknown", False)


class TestTheEntityHasNoPathThatKeepsTheOriginal:

    def test_recording_reduces_both_values(self):
        visit = LinkVisit.record(
            link_id="link-1",
            remote_addr="203.0.113.42",
            user_agent="Mozilla/5.0 (iPhone) AppleWebKit/605 Mobile Safari/604",
        )

        assert visit.visitor_network == "203.0.113.0"
        assert visit.device == "mobile"

        # The address and the header are not on the entity at all: there is
        # nothing to accidentally persist, log or serialise later.
        stored = vars(visit)
        assert "203.0.113.42" not in str(stored)
        assert "iPhone" not in str(stored)

    def test_every_visit_gets_its_own_identity_and_a_time(self):
        first = LinkVisit.record(link_id="link-1")
        second = LinkVisit.record(link_id="link-1")

        assert first.id != second.id
        assert first.occurred_at.tzinfo is not None


class TestWhatAVisitIsWhenNothingSaidOtherwise:
    """
    The defaults a visit records with, which are what a request that
    carried no header gets.

    ``is_bot`` is the one that decides arithmetic: every chart and every
    total splits on it, and a visit defaulting to ``True`` would count
    ordinary traffic as robots on the panel an operator reads. Flipping
    the default left the whole suite green -- measured -- because the
    tests above always pass a header that decides the value.
    """

    def test_a_visit_with_no_header_is_not_a_robot(self):
        assert LinkVisit.record(link_id="link-1").is_bot is False

    def test_a_visit_built_field_by_field_is_not_a_robot_either(self):
        """Not through ``record``, which decides the flag from the header:
        the field's own default. It is what a row rebuilt without that
        column gets, and a default of ``True`` there counts ordinary
        traffic as robots on every chart."""
        from datetime import datetime, timezone

        visit = LinkVisit(
            id="visit-1", link_id="link-1",
            occurred_at=datetime.now(timezone.utc),
        )

        assert visit.is_bot is False

    def test_a_visit_with_no_header_has_no_device_or_browser_named(self):
        visit = LinkVisit.record(link_id="link-1")

        assert visit.device == "unknown"
        assert visit.browser == "unknown"

    def test_a_visit_with_no_address_keeps_no_network(self):
        assert LinkVisit.record(link_id="link-1").visitor_network is None

    def test_a_robot_that_announced_itself_is_marked(self):
        """The other side of the same field, so the default is a default
        rather than the only answer the entity can give."""
        visit = LinkVisit.record(
            link_id="link-1",
            user_agent="Mozilla/5.0 (compatible; Googlebot/2.1)",
        )

        assert visit.is_bot is True
