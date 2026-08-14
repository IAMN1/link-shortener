"""What a deployed profile refuses to validate without.

``BaseConfig.validate`` reads settings. Three of the things a deployed
profile cannot start without are not reached there: the database URL is
assembled from several settings only when something asks for it, an
absent ``DOMAIN`` is a documented fallback rather than an error, and
``REDIS_URL`` sits behind a short-circuiting ``CACHE_ENABLED and
REDIS_ENABLED and not REDIS_URL`` that skips it whenever the cache is
off. So the check passed over all three and the deployment failed later
-- at the first connection, the first link handed out, or the assembly of
the rate limiter -- and never at the check written to catch it.

Both profiles close it with a ``validate`` of their own. Without one,
every test below passes against a profile whose docstring says it mirrors
production.

The profiles here are built from the **environment**, not from pinned
class attributes, and that is the point rather than a style choice. Every
setting this file is about is a lazy property or an on-demand assembly;
pinning ``SECRET_KEY`` or ``REDIS_URL`` as a plain attribute shadows the
property by MRO, so the code under test never runs and the assertion
becomes one about the fixture: with those pinned, deleting the whole Redis
branch from ``staging.validate()`` leaves this file green.

``detached_env`` empties the environment and points the project root at
an empty directory, so what a test sets is the entire configuration and
the developer's own ``.env`` cannot answer for it.
"""

import pytest

from link_shortener.infrastructure.configs.app.production import (
    ProductionConfig
)
from link_shortener.infrastructure.configs.app.staging import StagingConfig


pytestmark = pytest.mark.usefixtures("detached_env")


DEPLOYED_PROFILES = {
    "staging": StagingConfig,
    "production": ProductionConfig,
}

FULLY_CONFIGURED = {
    "SECRET_KEY": "not-the-generated-default",
    "SHORT_CODE_PEPPER": "not-the-generated-default",
    "DOMAIN": "links.example.com",
    "REDIS_ENABLED": "false",
    "DATABASE_TYPE": "postgresql",
    "DATABASE_USER": "shortener",
    "DATABASE_PASSWORD": "s3cret",
    "DATABASE_HOST": "db.internal",
    "DATABASE_NAME": "shortener",
}
"""A deployment that settled everything either profile demands.

Written as environment variables, under the names an operator writes,
rather than as attributes: ``SHORT_CODE_PEPPER`` is the variable behind
the ``SHORT_CODE_SECRET_PEPPER`` property, and the difference is exactly
the kind of thing a test that pinned attributes could not see.

Redis is switched off rather than pointed somewhere, so that the tests
which do switch it on say so themselves.
"""


def validation_errors(monkeypatch, profile_cls, **overrides):
    """Collect what a profile complains about.

    Args:
        monkeypatch: Fixture used to write the environment.
        profile_cls: Profile to build and validate.
        **overrides: Environment values on top of ``FULLY_CONFIGURED``;
            ``None`` unsets the variable instead of writing it.

    Returns:
        The error text, or an empty string when the profile validates.
    """
    for name, value in {**FULLY_CONFIGURED, **overrides}.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)

    try:
        profile_cls().validate()
    except ValueError as e:
        return str(e)
    return ""


class TestTheDatabaseIsDemandedAtTheCheck:
    """At the check, not at the first connection."""

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_incomplete_postgresql_parts_are_refused(
        self, monkeypatch, name, profile_cls
    ):
        """The URL is assembled on demand, so it has to be demanded.

        A missing part is not a missing setting to ``BaseConfig``: the
        parts are all present as settings and only their combination is
        unusable, and nothing notices until something asks for the URL.
        """
        errors = validation_errors(monkeypatch, profile_cls, DATABASE_USER=None)

        assert "PostgreSQL connection requires" in errors, (
            f"profile {name} validated a URL it cannot build: {errors!r}"
        )


class TestThePublicAddressIsDemanded:
    """A deployed service has one, and it is not the bind address."""

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_a_missing_domain_is_refused(self, monkeypatch, name, profile_cls):
        """Unset, it is not an error anywhere -- it is a fallback.

        ``BASE_URL`` falls back to ``http://HOST:PORT/``, which is where
        the process binds rather than where the service is reached, and
        the ``USE_HTTPS`` a deployed profile turns on is not consulted on
        that path at all. So the service starts, answers, and hands out
        short links naming an internal host over plain HTTP.
        """
        errors = validation_errors(monkeypatch, profile_cls, DOMAIN=None)

        assert "DOMAIN" in errors, (
            f"profile {name} accepted no public domain: {errors!r}"
        )

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_a_blank_domain_is_refused_too(
        self, monkeypatch, name, profile_cls
    ):
        """``DOMAIN=`` in an env file is how it is unset in practice.

        The env descriptor treats a blank value as absent, and the check
        has to agree with it rather than with the raw string, or the one
        spelling an operator actually writes slips past.
        """
        errors = validation_errors(monkeypatch, profile_cls, DOMAIN="")

        assert "DOMAIN" in errors, (
            f"profile {name} accepted a blank public domain: {errors!r}"
        )


class TestRedisIsDemandedWheneverItIsSwitchedOn:
    """Including when the cache is off, which is where the base check ends.

    ``BaseConfig.validate`` asks ``CACHE_ENABLED and REDIS_ENABLED and
    not REDIS_URL``, and ``and`` short-circuits. With the cache off that
    expression stops at the first term and ``REDIS_URL`` is never read --
    but ``RateLimiterComponent`` reads it regardless of the cache, so the
    property raises during container assembly instead.
    """

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_redis_without_a_url_is_refused(
        self, monkeypatch, name, profile_cls
    ):
        errors = validation_errors(
            monkeypatch, profile_cls, REDIS_ENABLED="true", REDIS_URL=None
        )

        assert "REDIS_URL" in errors, (
            f"profile {name} accepted Redis with no URL: {errors!r}"
        )

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_redis_without_a_url_is_refused_with_the_cache_off(
        self, monkeypatch, name, profile_cls
    ):
        """The combination the base check cannot see.

        Without a ``validate`` on the profile itself, this configuration
        validates clean.
        """
        errors = validation_errors(
            monkeypatch,
            profile_cls,
            REDIS_ENABLED="true",
            REDIS_URL=None,
            CACHE_ENABLED="false",
        )

        assert "REDIS_URL" in errors, (
            f"profile {name} accepted Redis with no URL while the cache "
            f"was off: {errors!r}"
        )


class TestTheSecretsAreStillDemanded:
    """Held here so this file cannot claim coverage it does not have.

    These two are not the gap -- ``BaseConfig.validate`` reaches both --
    and that is exactly why they are asserted through the environment
    rather than assumed: a fixture that pinned them would silence the
    properties and leave the demand untested from either side.
    """

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_a_missing_secret_key_is_refused(
        self, monkeypatch, name, profile_cls
    ):
        errors = validation_errors(monkeypatch, profile_cls, SECRET_KEY=None)

        assert "SECRET_KEY" in errors, f"profile {name}: {errors!r}"

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_a_missing_pepper_is_refused(self, monkeypatch, name, profile_cls):
        errors = validation_errors(
            monkeypatch, profile_cls, SHORT_CODE_PEPPER=None
        )

        assert "SHORT_CODE_PEPPER" in errors, f"profile {name}: {errors!r}"


class TestASettledDeploymentStillValidates:
    """The other half: a demand nobody can satisfy stops a deployment.

    Without this, every assertion above is satisfiable by a profile that
    refuses everything, and the tests would still be green.
    """

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_a_fully_configured_profile_is_accepted(
        self, monkeypatch, name, profile_cls
    ):
        assert validation_errors(monkeypatch, profile_cls) == "", (
            f"profile {name} refused a settled deployment"
        )

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_redis_may_be_switched_on_when_it_has_a_url(
        self, monkeypatch, name, profile_cls
    ):
        """The cache is the one dependency these profiles allow either way."""
        errors = validation_errors(
            monkeypatch,
            profile_cls,
            REDIS_ENABLED="true",
            REDIS_URL="redis://cache.internal:6379/0",
        )

        assert errors == "", f"profile {name} refused a configured Redis"
