"""
The startup check held against the real application, not a stand-in.

``check_rate_limit_targets`` has unit tests of its own; what those cannot
say is that ``create_app`` ever calls it. Deleting the one line that does
left the whole suite green, and with it went every guarantee that a name
in the settings is a name the throttle reaches -- a misspelt
``auth.login`` quietly relaxes brute-force protection from five attempts
a minute to the default hundred.

Names, not numbers. That the shipped values are the values the
documentation publishes is asserted separately, in
tests/unit/infrastructure/test_config/test_secure_defaults.py, where a
profile can be read detached from the environment: a limit swapped from
``(5, 60)`` to ``(60, 5)`` passes every check in this file.

Built here rather than in tests/unit because the check reads the URL map,
and the URL map is only complete once every blueprint has been registered
against a real container.
"""

import pytest

from link_shortener.web.app_factory import create_app

from tests.integration.conftest import IntegrationTestConfig


class TestCreateAppChecksRateLimitTargets:
    """Tests that building the application applies the reachability check."""

    def _config_with(self, rate_limits):
        """
        Build a config carrying the given limits and nothing else changed.

        RATE_LIMITS is a mutable class attribute shared by every config, so
        the override is declared on a subclass instead of assigned into the
        inherited dict, which would leak into every later test.

        Args:
            rate_limits: Value for the RATE_LIMITS setting.

        Returns:
            A config instance ready to hand to create_app.
        """
        class PoisonedConfig(IntegrationTestConfig):
            RATE_LIMITS = rate_limits

        return PoisonedConfig()

    def test_an_exempt_endpoint_stops_the_application_being_built(self):
        """A limit on the probe is refused where the app is assembled."""
        with pytest.raises(ValueError) as exc_info:
            create_app(config=self._config_with({"health": (10, 5)}))

        assert "health" in str(exc_info.value)
        assert "EXEMPT_ENDPOINTS" in str(exc_info.value)

    def test_a_misspelt_endpoint_stops_the_application_being_built(self):
        """
        The failure a real deployment is far likelier to meet.

        `auth.login` mistyped is not a typo that shows up as an error: the
        endpoint keeps answering, on the default limit, and login goes from
        five attempts a minute to a hundred.
        """
        with pytest.raises(ValueError) as exc_info:
            create_app(config=self._config_with({"auth.log_in": (5, 60)}))

        assert "auth.log_in" in str(exc_info.value)
        assert "no route answers" in str(exc_info.value)

    def test_a_malformed_limit_stops_the_application_being_built(self):
        """
        A value that is not a pair unpacks into a 500, one request later.

        Reported at startup, where the setting is, rather than as an error
        from whichever endpoint is asked for first.
        """
        with pytest.raises(ValueError) as exc_info:
            create_app(config=self._config_with({"auth.login": 10}))

        assert "auth.login" in str(exc_info.value)
        assert "positive integers" in str(exc_info.value)

    def test_the_shipped_configuration_is_accepted(self):
        """
        The check passes what the application actually ships with.

        Without this the three refusals above are equally satisfied by a
        check that refuses everything.
        """
        app = create_app(config=IntegrationTestConfig())

        assert app.config["RATE_LIMITS"]
        app.container.close()
