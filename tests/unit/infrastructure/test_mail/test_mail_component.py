"""Which mailer a configuration produces, and with which settings.

The component is the only place that decides whether anything is sent at
all, so a mistake here is invisible: the suite goes on passing and a
deployment either sends nothing or opens sockets it was told not to.
"""

from unittest.mock import Mock

from link_shortener.infrastructure.di.components.mail import MailComponent
from link_shortener.infrastructure.mail.null_mailer import NullMailer
from link_shortener.infrastructure.mail.smtp_mailer import SMTPMailer


def component(**overrides):
    """Build a mail component with plausible settings.

    Args:
        **overrides: Settings to replace.

    Returns:
        A configured ``MailComponent``.
    """
    settings = {
        "mail_enabled": True,
        "host": "smtp.example.com",
        "port": 465,
        "username": "postmaster",
        "password": "s3cret",
        "sender": "no-reply@example.com",
        "use_tls": False,
        "use_ssl": True,
        "timeout": 7.5,
        "logger": Mock(),
    }
    settings.update(overrides)
    return MailComponent(**settings)


class TestWhichImplementation:
    """Enabled means SMTP; disabled means nothing leaves the process."""

    def test_enabled_produces_an_smtp_mailer(self):
        assert isinstance(component().get_mailer(), SMTPMailer)

    def test_disabled_produces_a_null_mailer(self):
        assert isinstance(
            component(mail_enabled=False).get_mailer(), NullMailer
        )

    def test_the_mailer_is_a_singleton(self):
        """Rebuilt per call, the connection settings would be fine and the
        object identity would not -- and identity is what a test double
        installed on the container relies on."""
        built = component()

        assert built.get_mailer() is built.get_mailer()


class TestWhatItPassesOn:
    """Every setting has to arrive; a dropped one fails silently."""

    def test_the_smtp_mailer_gets_the_whole_configuration(self):
        logger = Mock()

        mailer = component(logger=logger).get_mailer()

        assert mailer.host == "smtp.example.com"
        assert mailer.port == 465
        assert mailer.username == "postmaster"
        assert mailer.password == "s3cret"
        assert mailer.sender == "no-reply@example.com"
        assert mailer.use_tls is False
        assert mailer.use_ssl is True
        assert mailer.timeout == 7.5
        # The one that was missing from this list, and the one whose
        # absence is silent: without a logger an unreachable submission
        # server raises the same error and leaves no line behind saying
        # which server, or that anything was attempted at all.
        assert mailer.logger is logger

    def test_starttls_settings_survive_too(self):
        """The other branch of the pair, which a swap would hide."""
        mailer = component(port=587, use_tls=True, use_ssl=False).get_mailer()

        assert mailer.port == 587
        assert mailer.use_tls is True
        assert mailer.use_ssl is False

    def test_the_null_mailer_can_still_report(self):
        logger = Mock()

        component(mail_enabled=False, logger=logger).get_mailer()

        assert logger.info.called, "a deployment must be told mail is off"
