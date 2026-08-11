"""The mailer a deployment without mail gets.

Its whole job is to be uneventful -- accept the message, drop it, say so
once. The tests that matter are about what it must not do: fail, and
repeat the confirmation link into the log.
"""

from unittest.mock import Mock

from link_shortener.infrastructure.mail.null_mailer import NullMailer


class TestItAcceptsAndDrops:
    """A service configured without mail still has to serve links."""

    def test_sending_without_a_logger_is_silent(self):
        NullMailer().send("user@example.com", "Confirm", "text")

    def test_it_records_that_a_message_was_dropped(self):
        logger = Mock()

        NullMailer(logger=logger).send("user@example.com", "Confirm", "text")

        args, kwargs = logger.info.call_args
        assert kwargs["to"] == "user@example.com"
        assert kwargs["subject"] == "Confirm"

    def test_the_body_never_reaches_the_log(self):
        """The body carries the link, and the link confirms the address.

        Anything that can read the log could then confirm an address it
        does not own -- which is the whole guarantee the mail channel
        exists to provide.

        Asserted over every call the logger received rather than over
        ``logger.info`` alone: a second line at DEBUG carrying the body
        would satisfy a check that reads one method and defeat the rule
        entirely.
        """
        logger = Mock()

        NullMailer(logger=logger).send(
            "user@example.com",
            "Confirm",
            "Open https://x.example/verify?token=SECRET-TOKEN",
        )

        assert "SECRET-TOKEN" not in str(logger.mock_calls)
