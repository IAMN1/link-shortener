"""Mail settings that are syntactically fine and cannot work.

Every combination refused here would otherwise fail in the same shape: the
request succeeds, the log says the message was handed over, and the person
waiting for it never receives anything. A startup error is the only place
that failure is cheap.

The profiles are read detached from the environment, so these answer the
question an operator actually has -- what happens if I set nothing -- and
not what happens to be exported in this shell.
"""

import pytest

from link_shortener.infrastructure.configs.app.base import BaseConfig
from link_shortener.infrastructure.configs.app.development import DevelopmentConfig
from link_shortener.infrastructure.configs.app.production import ProductionConfig
from link_shortener.infrastructure.configs.app.staging import StagingConfig
from link_shortener.infrastructure.configs.app.testing import TestingConfig


PROFILES = {
    "base": BaseConfig,
    "development": DevelopmentConfig,
    "staging": StagingConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}

DEPLOYED_PROFILES = {
    "staging": StagingConfig,
    "production": ProductionConfig,
}


SATISFIED_ELSEWHERE = {
    "SECRET_KEY": "not-the-generated-default",
    "SHORT_CODE_SECRET_PEPPER": "not-the-generated-default",
    "DOMAIN": "links.example.com",
    "REDIS_ENABLED": False,
    "DATABASE_URL": "postgresql+psycopg://u:p@db.internal:5432/short",
}
"""Settings the deployed profiles want before they look at mail.

Pinned so these tests measure the mail rules and nothing else. Left out,
``ProductionConfig.validate()`` raises about ``SECRET_KEY`` from a property
before any list of errors is assembled, and every assertion below would be
reading that message instead. ``DATABASE_URL`` is here for the same
reason and not because these tests connect to anything: a deployed
profile runs on PostgreSQL and refuses every other backend, which is
``test_deployed_profiles_run_on_postgresql``'s subject, not this
module's.
"""


def config(profile_cls=BaseConfig, **attrs):
    """Build a profile detached from the environment.

    Args:
        profile_cls: Profile to derive from.
        **attrs: Settings to pin as plain attributes, which shadow the
            environment-backed descriptors.

    Returns:
        An instance answering only from its own defaults.
    """
    detached = type("Detached", (profile_cls,), {"IGNORE_ENV": True, **attrs})
    return detached()


def mail_errors(profile_cls=BaseConfig, **attrs):
    """Collect the mail complaints a configuration raises.

    Goes through ``validate()`` rather than calling the private helper, so
    a helper that stopped being wired into validation fails this too.

    Args:
        profile_cls: Profile to derive from.
        **attrs: Settings to pin.

    Returns:
        The error text, or an empty string when the configuration is valid.
    """
    try:
        config(profile_cls, **{**SATISFIED_ELSEWHERE, **attrs}).validate()
    except ValueError as e:
        return str(e)
    return ""


WORKING_MAIL = {
    "MAIL_ENABLED": True,
    "MAIL_HOST": "smtp.example.com",
    "MAIL_FROM": "no-reply@example.com",
}


class TestACoherentConfigurationPasses:
    """The baseline the refusals below are measured against."""

    def test_starttls_submission_is_accepted(self):
        assert mail_errors(**WORKING_MAIL) == ""

    def test_implicit_tls_submission_is_accepted(self):
        assert mail_errors(
            **WORKING_MAIL,
            MAIL_PORT=465,
            MAIL_USE_TLS=False,
            MAIL_USE_SSL=True,
        ) == ""

    def test_authenticated_submission_is_accepted(self):
        assert mail_errors(
            **WORKING_MAIL, MAIL_USERNAME="postmaster", MAIL_PASSWORD="s3cret"
        ) == ""

    def test_a_disabled_channel_needs_no_host_or_sender(self):
        """Nothing intends to submit, so nothing is demanded."""
        assert mail_errors(MAIL_ENABLED=False, MAIL_HOST="", MAIL_FROM="") == ""


class TestTransportCombinationsThatCannotWork:
    """Checked whether or not the channel is on: they are typos either way."""

    def test_both_tls_modes_at_once_are_refused(self):
        """STARTTLS inside an established TLS session is a protocol error.

        Refused rather than silently preferred, because a deployment that
        set both meant one of them and would otherwise never learn which
        it got.
        """
        assert "mutually exclusive" in mail_errors(
            MAIL_USE_TLS=True, MAIL_USE_SSL=True
        )

    @pytest.mark.parametrize("port", [0, -1, 65536])
    def test_an_impossible_port_is_refused(self, port):
        assert "MAIL_PORT" in mail_errors(MAIL_PORT=port)

    @pytest.mark.parametrize("timeout", [0, -1.0, float("inf"), float("nan")])
    def test_a_timeout_that_is_not_a_bound_is_refused(self, timeout):
        """Zero and negative are not "no timeout" to socket code, and
        infinity is exactly the wait this setting exists to prevent."""
        assert "MAIL_TIMEOUT" in mail_errors(MAIL_TIMEOUT=timeout)

    def test_a_disabled_channel_still_reports_a_bad_port(self):
        """The typo is a typo now; finding it later costs a deployment."""
        assert "MAIL_PORT" in mail_errors(MAIL_ENABLED=False, MAIL_PORT=0)


class TestWhatAnEnabledChannelMustHave:
    """Settings demanded only once something intends to submit."""

    def test_a_host_is_required(self):
        assert "MAIL_HOST" in mail_errors(MAIL_ENABLED=True, MAIL_FROM="a@b.co")

    def test_the_host_has_no_default_to_hide_behind(self):
        """The check above is only reachable because this is empty.

        A blank environment variable reads as unset, so any default here
        would be what validation sees -- the requirement would pass for a
        deployment that never named a server, and the first registration
        would spend the mail timeout talking to nobody.
        """
        assert config(BaseConfig).MAIL_HOST == ""

    def test_a_sender_is_required(self):
        assert "MAIL_FROM" in mail_errors(
            MAIL_ENABLED=True, MAIL_HOST="smtp.example.com"
        )

    @pytest.mark.parametrize(
        "sender",
        [
            "not-an-address",
            "no-reply@example.com\n",
            "no-reply@example.com\r\nBcc: evil@example.com",
            "no-reply@example.com\x1f",
            "two@at@example.com",
            "no-reply@localhost",
        ],
    )
    def test_a_sender_that_is_not_an_address_is_refused(self, sender):
        """This value becomes a From header.

        The line-break cases are the ones that matter: a newline in a
        header is how a header injection is spelled, and a sender is
        configuration, so nothing else would ever have validated it.
        """
        assert "MAIL_FROM" in mail_errors(
            MAIL_ENABLED=True, MAIL_HOST="smtp.example.com", MAIL_FROM=sender
        )

    def test_a_password_with_nothing_to_authenticate_is_refused(self):
        """Set alone it is never used, which reads like it is."""
        assert "MAIL_PASSWORD" in mail_errors(
            **WORKING_MAIL, MAIL_PASSWORD="s3cret"
        )

    def test_a_username_with_no_password_is_refused(self):
        """The mirror of the case above, and the one that happens.

        A blank environment variable reads as unset and ``docker compose``
        substitutes a blank for every ``${VAR}`` missing from the env
        file, so a mislaid ``MAIL_PASSWORD`` leaves a username standing
        alone. That configuration starts cleanly and then fails
        authentication on every single message -- the failure furthest
        from where anyone looks for it.
        """
        assert "MAIL_USERNAME" in mail_errors(
            **WORKING_MAIL, MAIL_USERNAME="postmaster"
        )


class TestCredentialsNeedAnEncryptedChannel:
    """A password submitted in the clear is a password published."""

    def test_a_username_without_any_tls_is_refused(self):
        assert "MAIL_USERNAME" in mail_errors(
            **WORKING_MAIL,
            MAIL_USERNAME="postmaster",
            MAIL_PASSWORD="s3cret",
            MAIL_USE_TLS=False,
        )

    def test_implicit_tls_satisfies_the_requirement(self):
        """RFC 8314 treats the two ports as equivalent; so does this."""
        assert mail_errors(
            **WORKING_MAIL,
            MAIL_USERNAME="postmaster",
            MAIL_PASSWORD="s3cret",
            MAIL_USE_TLS=False,
            MAIL_USE_SSL=True,
            MAIL_PORT=465,
        ) == ""


class TestDeployedProfilesRequireEncryption:
    """Development may aim at a local catcher; a deployment may not."""

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_plain_submission_is_refused(self, name, profile_cls):
        errors = mail_errors(
            profile_cls, **WORKING_MAIL, MAIL_USE_TLS=False, MAIL_USE_SSL=False
        )
        assert "MAIL_USE_TLS or MAIL_USE_SSL" in errors, (
            f"profile {name} would submit mail in the clear"
        )

    @pytest.mark.parametrize("name, profile_cls", DEPLOYED_PROFILES.items())
    def test_the_requirement_is_not_a_setting(self, name, profile_cls):
        """Overridable, it would be overridden by the first host that
        cannot get TLS working, and never put back.

        Asserted on what the attribute *is*, not on what it answers.
        Reading ``profile_cls.REQUIRE_MAIL_TLS`` cannot tell the two
        apart: ``EnvField.__get__`` serves class access too and hands back
        its default, so an ``env_bool("REQUIRE_MAIL_TLS", True)`` here --
        exactly the change this test exists to forbid -- answers ``True``
        and passes.
        """
        declared = vars(profile_cls).get("REQUIRE_MAIL_TLS")

        assert declared is True, (
            f"profile {name} does not require encrypted submission as a "
            f"plain attribute: {declared!r}"
        )

    def test_development_may_talk_to_a_local_catcher(self):
        """Mailpit speaks no TLS and the traffic never leaves the machine."""
        assert DevelopmentConfig.REQUIRE_MAIL_TLS is False

    def test_a_deployed_profile_with_tls_is_accepted(self):
        """The refusal above has to be about TLS and nothing else."""
        assert mail_errors(ProductionConfig, **WORKING_MAIL) == ""


class TestDefaultsADeploymentInherits:
    """What happens when an operator configures nothing at all."""

    @pytest.mark.parametrize("name, profile_cls", PROFILES.items())
    def test_mail_is_off_until_it_is_configured(self, name, profile_cls):
        """An unconfigured channel that tried would be a socket timeout on
        the registration path, aimed at whatever localhost answers."""
        assert config(profile_cls).MAIL_ENABLED is False, (
            f"profile {name} would attempt to send mail out of the box"
        )

    @pytest.mark.parametrize(
        "name, profile_cls",
        {**DEPLOYED_PROFILES, "base": BaseConfig}.items(),
    )
    def test_encryption_is_the_default_where_it_can_be(self, name, profile_cls):
        """A default that has to be switched on is one nobody switches on."""
        assert config(profile_cls).MAIL_USE_TLS is True, (
            f"profile {name} would submit mail unencrypted by default"
        )

    def test_the_submission_port_is_the_submission_port(self):
        """587 is the STARTTLS submission port, which is what the default
        TLS setting expects. Compared against the number rather than
        against the setting, which would compare a value with itself."""
        assert config(BaseConfig).MAIL_PORT == 587

    def test_development_points_at_the_local_catcher(self):
        """1025 and no TLS is what the Mailpit container offers."""
        dev = config(DevelopmentConfig)

        assert dev.MAIL_HOST == "localhost"
        assert dev.MAIL_PORT == 1025
        assert dev.MAIL_USE_TLS is False

    def test_the_timeout_is_bounded_out_of_the_box(self):
        assert 0 < config(BaseConfig).MAIL_TIMEOUT < 60


class TestTheTwoConfirmationLifetimes:
    """How long a link lives, and how long the account behind it does."""

    def test_an_account_may_not_be_swept_before_its_link_expires(self):
        """The person following a link that is still valid would be told
        it is not, because the account it names was deleted underneath."""
        errors = mail_errors(
            EMAIL_VERIFICATION_TTL_HOURS=48, UNVERIFIED_ACCOUNT_TTL_HOURS=24
        )

        assert "UNVERIFIED_ACCOUNT_TTL_HOURS" in errors

    def test_equal_lifetimes_are_allowed(self):
        """The boundary: the account outlives the link by exactly nothing,
        which is enough."""
        assert mail_errors(
            EMAIL_VERIFICATION_TTL_HOURS=24, UNVERIFIED_ACCOUNT_TTL_HOURS=24
        ) == ""

    @pytest.mark.parametrize(
        "name", ["EMAIL_VERIFICATION_TTL_HOURS", "UNVERIFIED_ACCOUNT_TTL_HOURS"]
    )
    @pytest.mark.parametrize("value", [0, -1])
    def test_a_lifetime_must_be_positive(self, name, value):
        """Zero hours is not "immediately" -- it is a link that expired
        before it was mailed, and a sweep that deletes accounts as they
        register."""
        assert name in mail_errors(**{name: value})

    def test_the_lifetimes_are_checked_with_mail_switched_off(self):
        """The sweep runs on its own schedule and never asks whether
        anything was mailed."""
        errors = mail_errors(
            MAIL_ENABLED=False,
            EMAIL_VERIFICATION_TTL_HOURS=48,
            UNVERIFIED_ACCOUNT_TTL_HOURS=24,
        )

        assert "UNVERIFIED_ACCOUNT_TTL_HOURS" in errors

    def test_the_defaults_are_coherent(self):
        """What a deployment that configures neither one inherits."""
        settings = config(BaseConfig)

        assert settings.EMAIL_VERIFICATION_TTL_HOURS == 24
        assert settings.UNVERIFIED_ACCOUNT_TTL_HOURS == 72
        assert mail_errors() == ""


class TestTheSuiteCannotSendMail:
    """A test run must not reach a mail server on any machine."""

    def test_the_environment_cannot_switch_mail_on(self, monkeypatch):
        """``MAIL_ENABLED`` is a plain attribute on the testing profile, so
        it shadows the descriptor entirely -- not merely detached by
        ``IGNORE_ENV``, which a subclass could undo.

        Measured through a subclass that undoes exactly that. Setting the
        variable against plain ``TestingConfig`` proves nothing: with
        ``IGNORE_ENV`` on, a descriptor would return its default and the
        assertion would pass whether the attribute were here or inherited.
        ``tests/integration/conftest.py`` builds such subclasses, so this
        is the shape the suite actually runs in.
        """
        monkeypatch.setenv("MAIL_ENABLED", "true")
        attached = type("Attached", (TestingConfig,), {"IGNORE_ENV": False})

        assert attached().MAIL_ENABLED is False

    def test_it_is_the_attribute_and_not_the_detachment(self):
        """The same rule read off the class, so the reason is named."""
        assert vars(TestingConfig).get("MAIL_ENABLED") is False

    def test_the_container_hands_out_a_mailer_that_sends_nothing(self):
        from link_shortener.infrastructure.di.container import Container
        from link_shortener.infrastructure.mail.null_mailer import NullMailer

        container = Container(TestingConfig())
        try:
            assert isinstance(container.get_mailer(), NullMailer)
        finally:
            container.close()
