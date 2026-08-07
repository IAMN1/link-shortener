"""Settings whose default is itself a security decision.

Every one of these was, at some point, only as safe as the literal written
next to it. A mutation run flipping ``ALLOW_INTERNAL_TARGETS`` to ``True``
left all 1182 tests green: the suite exercised the setting's effect through
configurations that set it explicitly, so nothing was watching the default
that a real deployment inherits.

These tests read the defaults out of the profile classes rather than through
a fixture, so they answer the question an operator actually has: what happens
if I set nothing.
"""

import pytest

from link_shortener.infrastructure.configs.app.base import BaseConfig
from link_shortener.infrastructure.configs.app.development import DevelopmentConfig
from link_shortener.infrastructure.configs.app.production import ProductionConfig
from link_shortener.infrastructure.configs.app.staging import StagingConfig


PROFILES = {
    "base": BaseConfig,
    "development": DevelopmentConfig,
    "staging": StagingConfig,
    "production": ProductionConfig,
}


def default(profile_cls, name):
    """Read a setting from a profile detached from the environment.

    Args:
        profile_cls: Profile to read from.
        name: Setting name.

    Returns:
        The value a deployment gets when it configures nothing.
    """
    detached = type("Detached", (profile_cls,), {"IGNORE_ENV": True})()
    return getattr(detached, name)


class TestOutboundRequestsAreClosedByDefault:
    """Reaching internal addresses must be opted into, never inherited."""

    @pytest.mark.parametrize("name, profile_cls", PROFILES.items())
    def test_internal_targets_are_refused(self, name, profile_cls):
        """The flag that decides whether the service can be aimed inwards.

        Left on, a shortened link becomes a way to make the server fetch
        cloud metadata or reach a neighbour it can see and the caller
        cannot.
        """
        assert default(profile_cls, "ALLOW_INTERNAL_TARGETS") is False, (
            f"profile {name} would allow internal targets out of the box"
        )


class TestCookiesCarryTheirFlags:
    """Session cookies are the credential; their flags are the protection."""

    @pytest.mark.parametrize("name, profile_cls", PROFILES.items())
    def test_httponly_is_on(self, name, profile_cls):
        """Script-readable session cookies defeat the point of HttpOnly."""
        assert default(profile_cls, "SESSION_COOKIE_HTTPONLY") is True, (
            f"profile {name} would expose session cookies to scripts"
        )

    @pytest.mark.parametrize("name", ["staging", "production"])
    def test_secure_is_on_where_there_is_tls(self, name):
        """Deployed profiles must not send the cookie over plain HTTP.

        Development is exempt on purpose -- it runs without TLS, and a
        Secure cookie there would simply never be sent.
        """
        assert default(PROFILES[name], "SESSION_COOKIE_SECURE") is True, (
            f"profile {name} would send session cookies over plain HTTP"
        )


class TestRateLimitingIsOnByDefault:
    """The switch that turns the brute-force protection off entirely."""

    @pytest.mark.parametrize("name, profile_cls", PROFILES.items())
    def test_auth_rate_limiting_is_not_disabled(self, name, profile_cls):
        assert default(profile_cls, "RATE_LIMIT_AUTH_DISABLED") is False, (
            f"profile {name} ships with auth rate limiting switched off"
        )


class TestSchemaIsManagedByMigrations:
    """``USE_ALEMBIC`` decides which of two schema strategies is in force."""

    @pytest.mark.parametrize("name", ["base", "development", "staging", "production"])
    def test_alembic_is_the_default(self, name):
        """Everything but the test profile builds the schema from revisions."""
        assert default(PROFILES[name], "USE_ALEMBIC") is True
