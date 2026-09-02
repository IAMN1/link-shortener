"""Where the reset link points, and what is never written down about it.

The same three questions the confirmation message answers, asked again
because the answers are worth more here. A ``Host`` header an attacker
chose would mail the victim a link to the attacker's server carrying a
working token -- for the confirmation that costs an address, for this one
it costs the account. And the token in a log outlives the token in a
mailbox, which is why the failure path is checked as well as the success.
"""

from unittest.mock import Mock

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.mailer import MailDeliveryError
from link_shortener.application.use_cases.auth.send_password_reset_email import (
    SendPasswordResetEmailUseCase,
)


def context() -> RequestContext:
    """
    The request the message is being sent for.

    Returns:
        A context with no language chosen, as a queued task may have.
    """
    return RequestContext(request_id="req-1", remote_addr="203.0.113.7")


def a_use_case(mailer=None, logger=None, base_url="https://links.example.com"):
    """
    The use case over mocked collaborators.

    Args:
        mailer: Transport to hand the message to.
        logger: Application logger.
        base_url: Base the link is built on.

    Returns:
        Tuple of the use case and the templates mock, so a test can read
        what the message was asked to say.
    """
    templates = Mock()
    templates.password_reset_email.return_value = ("Reset", "body")
    if logger is None:
        logger = Mock()
        logger.bind.return_value = logger
    return SendPasswordResetEmailUseCase(
        mailer=mailer or Mock(),
        templates=templates,
        logger=logger,
        base_url=base_url,
        ttl_minutes=60,
    ), templates


class TestTheLink:
    """What the reader is given, and where it points."""

    def test_it_is_built_from_the_configured_base(self):
        """OWASP names this case outright: do not build a reset URL from
        the Host header."""
        use_case, templates = a_use_case()

        use_case.execute("user@example.com", "TOKEN-123", context())

        url = templates.password_reset_email.call_args.kwargs["reset_url"]
        # The page, not the endpoint -- and here the page is the only
        # possible arrangement, because the new password does not exist
        # until somebody types it.
        assert url.startswith("https://links.example.com/reset-password?token=")

    def test_a_trailing_slash_does_not_double(self):
        use_case, templates = a_use_case(base_url="https://links.example.com/")

        use_case.execute("user@example.com", "TOKEN-123", context())

        url = templates.password_reset_email.call_args.kwargs["reset_url"]
        assert "//reset-password" not in url

    def test_the_token_is_escaped_for_a_query_string(self):
        use_case, templates = a_use_case()

        use_case.execute("user@example.com", "a b&c=d", context())

        url = templates.password_reset_email.call_args.kwargs["reset_url"]
        assert url.endswith("token=a%20b%26c%3Dd")

    def test_the_reader_is_told_how_long_the_link_lives(self):
        use_case, templates = a_use_case()

        use_case.execute("user@example.com", "TOKEN-123", context())

        # In minutes, which is the unit the message is written in: a
        # reader told "1 hour" comes back to it in the evening.
        assert templates.password_reset_email.call_args.kwargs["ttl_minutes"] == 60


class TestWhenItCannotBeSent:
    """The failure has to reach the caller, and take nothing with it."""

    def test_a_delivery_failure_reaches_the_caller(self):
        """Swallowed here, the queue would count a lost message as sent
        and the retry would never happen -- leaving somebody locked out
        and waiting."""
        mailer = Mock()
        mailer.send.side_effect = MailDeliveryError("server down")
        use_case, _ = a_use_case(mailer=mailer)

        with pytest.raises(MailDeliveryError):
            use_case.execute("user@example.com", "TOKEN-123", context())


class TestWhatIsNeverLogged:
    """The one class that holds this token in the clear."""

    def test_a_sent_message_logs_no_token(self):
        logger = Mock()
        logger.bind.return_value = logger
        use_case, _ = a_use_case(logger=logger)

        use_case.execute("user@example.com", "SECRET-TOKEN-VALUE", context())

        assert "SECRET-TOKEN-VALUE" not in str(logger.mock_calls)

    def test_a_failed_delivery_logs_no_token_either(self):
        logger = Mock()
        logger.bind.return_value = logger
        mailer = Mock()
        mailer.send.side_effect = MailDeliveryError("server down")
        use_case, _ = a_use_case(mailer=mailer, logger=logger)

        with pytest.raises(MailDeliveryError):
            use_case.execute("user@example.com", "SECRET-TOKEN-VALUE", context())

        # The branch that is easiest to get wrong: an error log that says
        # "could not send this link" with the link in it.
        assert "SECRET-TOKEN-VALUE" not in str(logger.mock_calls)
