"""
The published rate limits against the ones the service enforces.

The configuration reference prints these numbers as the service's promise, and until now
nothing read them: the tables drifted from the configuration and from each
other, and the drift was found by hand. A limit is a security decision,
and a document that names the wrong one is worse than a document that
names none -- it is believed.

The tables are parsed rather than duplicated here. Copying the numbers
into a third place would make this test agree with itself.
"""

import re
from pathlib import Path

import pytest

from link_shortener.infrastructure.configs.app.base import BaseConfig


DOCS = Path("docs/configuration.md")

ROW = re.compile(
    r"^\|\s*`(?P<endpoint>[a-z_.]+)`\s*\|\s*(?P<limit>\d+)\s*\|\s*"
    r"(?P<period>\d+)\s*s\s*\|"
)


def documented_limits():
    """
    Read the endpoint table out of the operations guide.

    Returns:
        Mapping of endpoint name to ``(limit, period_seconds)``.
    """
    limits = {}
    for line in DOCS.read_text(encoding="utf-8").splitlines():
        match = ROW.match(line)
        if match:
            limits[match["endpoint"]] = (
                int(match["limit"]), int(match["period"])
            )
    return limits


def shipped_limits():
    """
    Read the limits a deployment gets when it configures nothing.

    Returns:
        The shipped ``RATE_LIMITS`` mapping.
    """
    detached = type("Detached", (BaseConfig,), {"IGNORE_ENV": True})()
    return detached.RATE_LIMITS


class TestTheTablesSayWhatTheServiceDoes:
    """The operations guide against ``RATE_LIMITS``.

    One table, in one document: the limits are an operations matter, and a
    copy in the README is a second place for the numbers to drift.
    """

    def test_the_guide_lists_every_configured_endpoint(self):
        """A limit that exists and is not published is a limit nobody plans for."""
        assert set(documented_limits()) == set(shipped_limits())

    @pytest.mark.parametrize("endpoint", sorted(shipped_limits()))
    def test_the_guide_prints_the_numbers_that_are_enforced(self, endpoint):
        """
        Every row, both numbers.

        Args:
            endpoint: Endpoint name, one test per row.
        """
        assert documented_limits()[endpoint] == shipped_limits()[endpoint]

    def test_the_documented_default_is_the_configured_one(self):
        """
        The pair that bounds everything the table does not name.

        Stated in prose beside the table, which is the sentence a reader
        uses to work out what an unlisted route costs.
        """
        detached = type("Detached", (BaseConfig,), {"IGNORE_ENV": True})()
        limit = detached.DEFAULT_RATE_LIMIT

        # Whitespace is collapsed first: the sentence is wrapped by the
        # markdown around it, and a check that depends on where the line
        # happens to break fails on a reflow that changed nothing.
        prose = " ".join(DOCS.read_text(encoding="utf-8").split())

        assert f"— {limit} requests per" in prose


class TestTheReadLimitsKeepTheirPlaceInTheOrder:
    """
    Not the numbers themselves -- the relations between them.

    Four of the fifteen entries are pinned -- ``auth.login``,
    ``auth.register``, ``auth.refresh_token`` and ``auth.logout`` -- along
    with the pair of defaults, because those stand against an attacker.
    The consequence was honest and unpleasant: ``redirect_to_original``
    could go from 200 to 200000 and no run would notice. Pinning all
    fifteen to literals would turn every deliberate retune into a red
    test, which is why it was not done. The other five ``auth.*`` limits
    -- the reset, verification and password-change endpoints -- are
    unpinned as well, which is worth knowing rather than assuming.

    What is asserted instead is the shape an operator relies on: reading is
    not cheaper to abuse than writing, nothing is effectively unlimited,
    and the endpoint that costs the most is not the loosest.
    """

    WRITES = ("api.create_short_link", "api.batch_create")
    READS = (
        "api.get_link_info",
        "api.get_extended_link_info",
        "api.get_stats",
        "redirect_to_original",
    )

    def limits(self):
        """
        Return the shipped table.

        Returns:
            Mapping of endpoint name to ``(limit, period_seconds)``.
        """
        return dict(BaseConfig.RATE_LIMITS)

    def test_every_read_endpoint_has_a_limit_at_all(self):
        """A missing key is not "unlimited by choice", it is a gap."""
        table = self.limits()

        assert set(self.READS) <= set(table)

    @pytest.mark.parametrize("endpoint", READS)
    def test_a_read_limit_stays_within_reach_of_the_default(self, endpoint):
        """Ten times the default is generous; two hundred times is not.

        This is the assertion that fails on ``200000`` while leaving an
        operator free to move 200 to 400.
        """
        limit, period = self.limits()[endpoint]

        assert 0 < limit <= BaseConfig.DEFAULT_RATE_LIMIT * 10, endpoint
        assert 0 < period <= 3600, endpoint

    def test_the_batch_endpoint_stays_the_tightest_of_all(self):
        """One request there is a hundred links; nothing may run freer.

        Not "writes are tighter than reads" -- that is simply not the
        table: creating a link is thirty a minute while reading statistics
        is ten, and rightly so, because the statistics query aggregates
        over every row. The relation that does hold, and that matters, is
        this one.
        """
        table = self.limits()
        rate = lambda name: table[name][0] / table[name][1]

        batch = rate("api.batch_create")
        others = [
            rate(name)
            for name in self.READS + ("api.create_short_link",)
        ]

        assert batch <= min(others)

    def test_a_single_redirect_may_run_freer_than_a_creation(self):
        """The cheap read against the write it serves.

        One redirect is one indexed lookup and a queued counter; one
        creation is a hash, a code search and a write. If the two ever
        swap places the table has been retuned by halves.
        """
        table = self.limits()
        rate = lambda name: table[name][0] / table[name][1]

        assert rate("redirect_to_original") > rate("api.create_short_link")

    def test_the_costliest_read_is_not_the_loosest_one(self):
        """``get_stats`` aggregates over every row; the redirect reads one.

        A table that let the expensive one run freer than the cheap one
        would be the wrong way round, however plausible each number looks
        on its own line.
        """
        table = self.limits()
        stats_rate = table["api.get_stats"][0] / table["api.get_stats"][1]
        redirect = table["redirect_to_original"]
        redirect_rate = redirect[0] / redirect[1]

        assert stats_rate <= redirect_rate
