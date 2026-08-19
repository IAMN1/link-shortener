"""
What a visit is allowed to remember about whoever made it.

A redirect knows an address and a User-Agent string, and both identify a
person well enough to be personal data. What the statistics actually need
is coarser: which network a visit came from, so two visits can be told
apart without either being traced back; and what kind of client made it,
so a browser and a crawler stop being counted as the same thing.

So the reduction happens here, before anything is stored, rather than in
the queries that read it later. A column that never held an address cannot
leak one, cannot be subpoenaed for one, and cannot be un-anonymised by a
later change of mind. Shlink stores an anonymised address for the same
reason, and Plausible stores none at all.
"""

import ipaddress
import re
from typing import Optional


def anonymise_address(address: Optional[str]) -> Optional[str]:
    """
    Reduce a client address to the network it came from.

    IPv4 loses its last octet, IPv6 everything below the /64 its provider
    hands out as one allocation. What is left distinguishes networks --
    enough to tell two sources apart on a chart -- and identifies no host.

    Args:
        address: Client address as the request reported it, if any.

    Returns:
        The network, written as an address with the host part zeroed
        (``203.0.113.0``, ``2001:db8::``). An IPv4-mapped address is
        reduced as the IPv4 address it carries, whatever the listener
        that spelled it that way. ``None`` when there was no
        address or it did not parse. An unparseable value is dropped
        rather than stored: it is either a proxy header nobody validated
        or something a caller made up, and neither belongs in a chart.
    """
    if not address:
        return None

    try:
        parsed = ipaddress.ip_address(address.strip())
    except ValueError:
        return None

    # An IPv4 client reaching a socket bound to `::` arrives written as
    # `::ffff:203.0.113.5`, and that is an IPv6 address by every test this
    # function can make -- including `.version`. Reduced as one it keeps
    # the /64, which for the whole IPv4-mapped range is `::`: every IPv4
    # visitor becomes one network. Unwrapped first, the address is reduced
    # by the rule for the family it actually belongs to. The deployment
    # decides which spelling arrives -- `HOST=::`, or nginx with
    # `ipv6only=off` -- so this cannot be left to the listener.
    mapped = getattr(parsed, "ipv4_mapped", None)
    if mapped is not None:
        parsed = mapped

    prefix = 24 if parsed.version == 4 else 64
    network = ipaddress.ip_network(f"{parsed}/{prefix}", strict=False)
    return str(network.network_address)


# Matched in the order written: the first pattern that fits wins, so the
# specific cases sit above the general ones. Edge and Chromium-based Opera
# both carry "Chrome" in their strings, and a check for Chrome placed first
# would swallow them.
_BROWSERS = (
    ("bot", re.compile(r"bot|crawler|spider|slurp|curl|wget|python-requests|"
                       r"headless|monitoring|preview|facebookexternalhit|"
                       r"whatsapp|telegrambot|slackbot", re.I)),
    ("edge", re.compile(r"edg[ea]?/", re.I)),
    ("opera", re.compile(r"opr/|opera", re.I)),
    ("samsung", re.compile(r"samsungbrowser", re.I)),
    ("firefox", re.compile(r"firefox/|fxios/", re.I)),
    ("chrome", re.compile(r"chrome/|crios/|chromium", re.I)),
    ("safari", re.compile(r"safari/", re.I)),
)

_MOBILE = re.compile(r"mobile|iphone|ipod|android.*mobile|windows phone", re.I)
_TABLET = re.compile(r"ipad|tablet|android(?!.*mobile)", re.I)


def classify_client(user_agent: Optional[str]) -> tuple[str, str, bool]:
    """
    Reduce a User-Agent string to the three facts a chart can use.

    Nothing here tries to be a full User-Agent database: those exist,
    need updating, and answer questions this service does not ask. The
    question here is only "browser or robot, and on what kind of screen".

    Args:
        user_agent: The header as sent, if it was sent at all.

    Returns:
        A triple of ``(device, browser, is_bot)``. ``device`` is one of
        ``desktop``, ``mobile``, ``tablet`` or ``unknown``; ``browser`` is
        a family name or ``unknown``; ``is_bot`` marks a client that
        announced itself as automated.

        Robots are recorded rather than dropped. A link posted to a chat
        gets fetched by the chat's own preview fetcher within seconds, and
        counting that as a reader is how a link appears to have been
        opened by somebody who never saw it -- but so is discarding it
        silently, because then the counter and the chart disagree and
        neither says why.
    """
    if not user_agent:
        return "unknown", "unknown", False

    browser = "unknown"
    is_bot = False
    for name, pattern in _BROWSERS:
        if pattern.search(user_agent):
            if name == "bot":
                is_bot = True
                browser = "bot"
            else:
                browser = name
            break

    if is_bot:
        # A crawler's device is a fiction: the string names whatever the
        # operator chose to imitate.
        return "unknown", browser, True

    # The tablet rule is tried first, and the order is the whole rule.
    # Every iPadOS string carries `Mobile/15E148` -- it has since iPadOS 13
    # made "request desktop site" the default -- so a phone rule that runs
    # first matches every iPad ever sold and `ipad` below it can never be
    # reached. Tried in this order, each pattern is asked the question it
    # can answer: `_TABLET` names the tablet outright (`ipad`, `tablet`) or
    # by an Android string with no `Mobile` in it, and whatever it does not
    # claim is left for `_MOBILE`, which no tablet string reaches.
    if _TABLET.search(user_agent):
        device = "tablet"
    elif _MOBILE.search(user_agent):
        device = "mobile"
    elif browser == "unknown":
        device = "unknown"
    else:
        device = "desktop"

    return device, browser, is_bot
