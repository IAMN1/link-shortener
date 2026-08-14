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

    @pytest.mark.parametrize("name, profile_cls", PROFILES.items())
    def test_the_brute_force_limits_are_the_documented_ones(self, name, profile_cls):
        """The numbers themselves, not merely that an entry exists.

        Reachability is not policy. ``auth.login`` swapped from ``(5, 60)``
        to ``(60, 5)`` is a reachable, well-formed entry that every startup
        check accepts, and it raises the password-guessing allowance from
        five attempts a minute to seven hundred and twenty -- with the
        comment beside it still reading "5 attempts per minute per IP".
        Only the four that exist to stop an attacker are pinned. Pinning
        all ten would turn every deliberate tuning of a read limit into a
        failing test, which is a different thing from a defect.

        docs/OPERATIONS_AND_MIGRATIONS.md publishes these numbers, so
        changing one is changing the document too.

        Args:
            name: Profile name, for the failure message.
            profile_cls: Profile to read from.
        """
        limits = default(profile_cls, "RATE_LIMITS")

        assert limits["auth.login"] == (5, 60), f"profile {name}"
        assert limits["auth.register"] == (3, 3600), f"profile {name}"
        assert limits["auth.refresh_token"] == (10, 60), f"profile {name}"
        assert limits["auth.logout"] == (20, 60), f"profile {name}"

    @pytest.mark.parametrize("name, profile_cls", PROFILES.items())
    def test_the_default_limit_is_the_documented_one(self, name, profile_cls):
        """The pair that bounds every route without an entry of its own.

        Most of the URL map -- the whole admin API, the dashboard, every
        page -- is held by this and by nothing else, so raising it silently
        raises the ceiling on far more traffic than any single row of the
        table does.

        Args:
            name: Profile name, for the failure message.
            profile_cls: Profile to read from.
        """
        assert default(profile_cls, "DEFAULT_RATE_LIMIT") == 100, (
            f"profile {name} ships a different default request ceiling"
        )
        assert default(profile_cls, "DEFAULT_RATE_LIMIT_PERIOD") == 60, (
            f"profile {name} ships a different default window"
        )

    @pytest.mark.parametrize("name, profile_cls", PROFILES.items())
    def test_the_middleware_falls_back_to_what_the_profiles_ship(
        self, name, profile_cls
    ):
        """The throttle's own fallback and the profiles' defaults agree.

        ``RateLimitMiddleware`` has to answer "what if neither is
        configured", and it answers with constants of its own. Left
        unpinned, an application assembled without a profile would be
        bounded by numbers nobody wrote down.

        Args:
            name: Profile name, for the failure message.
            profile_cls: Profile to read from.
        """
        from link_shortener.web.middleware.rate_limit import (
            FALLBACK_LIMIT, FALLBACK_PERIOD
        )

        assert default(profile_cls, "DEFAULT_RATE_LIMIT") == FALLBACK_LIMIT, (
            f"profile {name} disagrees with the middleware's fallback limit"
        )
        assert (
            default(profile_cls, "DEFAULT_RATE_LIMIT_PERIOD") == FALLBACK_PERIOD
        ), f"profile {name} disagrees with the middleware's fallback window"


class TestSchemaIsManagedByMigrations:
    """``USE_ALEMBIC`` decides which of two schema strategies is in force."""

    @pytest.mark.parametrize("name", ["base", "development", "staging", "production"])
    def test_alembic_is_the_default(self, name):
        """Everything but the test profile builds the schema from revisions."""
        assert default(PROFILES[name], "USE_ALEMBIC") is True


class TestDetachedProfilesReadNothingFromTheMachine:
    """``IGNORE_ENV`` has to hold for the mandatory secrets too.

    Every ``EnvField`` honoured the flag; the six ``@property`` settings that
    read the environment by hand -- ``SECRET_KEY``,
    ``SHORT_CODE_SECRET_PEPPER`` and ``REDIS_URL`` in both the production and
    the staging profile -- did not. A profile built to be read away from its
    machine, which is exactly what ``default()`` above builds, answered with
    this machine's secrets, and a test comparing them against a literal
    measured the machine.

    Detached, the variable reads as unset. These settings have no default to
    fall back on, so they refuse -- the same answer they give a deployment
    that configured nothing.
    """

    @pytest.mark.parametrize("profile_name", ["staging", "production"])
    @pytest.mark.parametrize(
        "setting, variable",
        [
            ("SECRET_KEY", "SECRET_KEY"),
            ("SHORT_CODE_SECRET_PEPPER", "SHORT_CODE_PEPPER"),
        ],
    )
    def test_a_secret_is_not_taken_from_the_environment(
        self, monkeypatch, profile_name, setting, variable
    ):
        monkeypatch.setenv(variable, "value-from-this-machine")
        detached = type(
            "Detached", (PROFILES[profile_name],), {"IGNORE_ENV": True}
        )()

        with pytest.raises(ValueError, match="must be set in environment"):
            getattr(detached, setting)

    @pytest.mark.parametrize("profile_name", ["staging", "production"])
    def test_the_redis_url_is_not_taken_from_the_environment(
        self, monkeypatch, profile_name
    ):
        monkeypatch.setenv("REDIS_URL", "redis://this-machine:6379/9")
        detached = type(
            "Detached", (PROFILES[profile_name],), {"IGNORE_ENV": True}
        )()

        # Redis is on by default in both profiles, so an unset URL is a
        # refusal rather than a blank.
        assert detached.REDIS_ENABLED is True
        with pytest.raises(ValueError, match="REDIS_URL must be set"):
            detached.REDIS_URL

    @pytest.mark.parametrize("profile_name", ["staging", "production"])
    def test_an_attached_profile_still_reads_them(
        self, monkeypatch, profile_name
    ):
        # The other half: detaching must not be the only way to read these.
        monkeypatch.setenv("SECRET_KEY", "value-from-this-machine")
        monkeypatch.setenv("SHORT_CODE_PEPPER", "pepper-from-this-machine")
        monkeypatch.setenv("REDIS_URL", "redis://this-machine:6379/9")
        attached = PROFILES[profile_name]()

        assert attached.SECRET_KEY == "value-from-this-machine"
        assert attached.SHORT_CODE_SECRET_PEPPER == "pepper-from-this-machine"
        assert attached.REDIS_URL == "redis://this-machine:6379/9"


class TestTheCookiesTheServiceActuallySets:
    """``COOKIE_SECURE`` is the flag on the tokens, and it was unpinned.

    ``SESSION_COOKIE_SECURE`` beside it is held by the class above -- but
    that one governs Flask's own signed session, which this service does not
    use. The access, refresh and CSRF cookies read ``COOKIE_SECURE``
    (`auth_controller`, `csrf`), and flipping its default sent all three to
    the browser without ``Secure``: tokens that travel over plain HTTP.
    """

    @pytest.mark.parametrize("name", ["staging", "production"])
    def test_the_token_cookies_are_https_only(self, name):
        assert default(PROFILES[name], "COOKIE_SECURE") is True, (
            f"profile {name} would send its tokens over plain HTTP"
        )


class TestRedisIsNotGuessedAtWhenItIsOff:
    """An address for a cache that was turned off is worse than none.

    ``production.REDIS_URL`` answers ``""`` when Redis is disabled, and its
    own docstring says why: a URL pointing at localhost would make the cache
    look configured while it quietly cached nothing. Nothing held the
    branch -- the detached profile raises before reaching it, and an
    attached one always has the variable set.
    """

    def test_production_answers_with_nothing(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        detached_off = type(
            "DetachedOff",
            (PROFILES["production"],),
            {"IGNORE_ENV": True, "REDIS_ENABLED": False},
        )()

        assert detached_off.REDIS_URL == ""


class TestBlankIsUnsetForTheMandatorySecrets:
    """``docker compose`` writes an empty string for every missing ``${VAR}``.

    The descriptors have read a blank as "not configured" all along; the six
    secret properties reach the environment through ``read_env_for``, and it
    has to apply the same rule. Read with a plain ``os.environ.get`` they
    would accept a key made of spaces -- which is what the comment in
    ``production.py`` says must not happen, and it would sign every token.
    """

    @pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
    @pytest.mark.parametrize("profile_name", ["staging", "production"])
    def test_a_blank_secret_counts_as_missing(
        self, monkeypatch, profile_name, blank
    ):
        monkeypatch.setenv("SECRET_KEY", blank)
        monkeypatch.setenv("SHORT_CODE_PEPPER", blank)
        profile = PROFILES[profile_name]()

        with pytest.raises(ValueError, match="SECRET_KEY must be set"):
            profile.SECRET_KEY
        with pytest.raises(ValueError, match="SHORT_CODE_PEPPER must be set"):
            profile.SHORT_CODE_SECRET_PEPPER
