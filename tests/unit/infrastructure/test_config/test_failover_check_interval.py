"""
How often the failover chains ask their implementations how they are.

The number decides two things a deployment cannot see any other way: how
long an implementation that has stopped writing keeps the work, and how
long one that recovered waits to get it back. Nothing read it. Measured
against the whole suite: the shipped default widened from 30 seconds to
3000 left it green, and the configuration's own validation passes such a
value happily -- it asks only for a positive finite number, which fifty
minutes is.

Read off a configuration detached from the environment. ``BaseConfig``'s
fields are lazy environment descriptors, so an attached instance answers
whatever ``FAILOVER_CHECK_INTERVAL`` happens to be set to on the machine
running the test, and the assertion would be about that machine.
"""

import pytest

from link_shortener.infrastructure.configs.app.base import BaseConfig


def shipped():
    """
    Build the configuration a deployment gets when it sets nothing.

    Returns:
        An instance detached from the environment (see ``IGNORE_ENV``).
    """
    return type("Detached", (BaseConfig,), {"IGNORE_ENV": True})()


class TestTheShippedInterval:

    def test_it_is_half_a_minute(self):
        # The literal is written here rather than read from the source: a
        # comparison against the constant it is built from moves with it.
        assert shipped().FAILOVER_CHECK_INTERVAL == 30.0

    def test_it_is_short_enough_to_be_a_health_check(self):
        """The bound that says what the number is *for*.

        A chain probed once an hour is not a chain with health checks; it
        is one with a slow scheduler. Stated as a bound as well as an
        equality so that a future change has to argue with the reason and
        not only with the number.
        """
        assert 0 < shipped().FAILOVER_CHECK_INTERVAL <= 60.0

    @pytest.mark.parametrize("value", ["45", "45.5"])
    def test_an_operator_can_set_it(self, monkeypatch, value):
        """
        Args:
            value: What the environment says, integer or fractional.
        """
        monkeypatch.setenv("FAILOVER_CHECK_INTERVAL", value)

        assert BaseConfig().FAILOVER_CHECK_INTERVAL == float(value)
