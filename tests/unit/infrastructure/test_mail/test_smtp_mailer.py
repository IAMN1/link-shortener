"""What the SMTP mailer does with a submission server, and refuses to.

No socket is opened anywhere here: ``smtplib`` is replaced by a recorder
that answers like a server and remembers what it was asked. That is the
only way to assert the things that matter -- that a timeout was passed,
that the password waited for encryption, that a failed connection became
one named error rather than whatever the network raised.
"""

import smtplib
import socket
import ssl
from unittest.mock import Mock

import pytest

from link_shortener.application.ports.mailer import MailDeliveryError
from link_shortener.infrastructure.mail.smtp_mailer import SMTPMailer


class RecordingSMTP:
    """Stands in for ``smtplib.SMTP`` and remembers the conversation.

    Attributes:
        sock: What the mailer inspects to decide whether the channel is
            encrypted. A plain ``socket.socket`` until ``starttls``
            replaces it, which is what the real class holds -- it was
            ``None`` here, and that let a check written as
            ``smtp.sock is None`` pass every test while telling an
            encrypted connection from a plain one nowhere but in this
            file. Verified against a real server: with that check the
            password went out in the clear.
    """

    instances = []

    def __init__(self, host=None, port=None, timeout=None, context=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.context = context
        self.sock = Mock(spec=socket.socket)
        self.starttls_calls = []
        self.ehlo_calls = 0
        self.logins = []
        self.sent = []
        self.exited = False
        self.quits = 0
        self.closes = 0
        RecordingSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.exited = True
        return False

    def starttls(self, context=None):
        self.starttls_calls.append(context)
        self.sock = Mock(spec=ssl.SSLSocket)

    def ehlo(self):
        self.ehlo_calls += 1

    def login(self, username, password):
        self.logins.append((username, password))

    def send_message(self, message):
        self.sent.append(message)

    def quit(self):
        self.quits += 1

    def close(self):
        self.closes += 1


class RecordingSMTPSSL(RecordingSMTP):
    """``smtplib.SMTP_SSL``: encrypted from the first byte."""

    def __init__(self, host=None, port=None, timeout=None, context=None):
        super().__init__(host, port, timeout, context)
        self.sock = Mock(spec=ssl.SSLSocket)


@pytest.fixture
def smtp(monkeypatch):
    """Replace both smtplib classes and hand back the recorded instances."""
    RecordingSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", RecordingSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", RecordingSMTPSSL)
    return RecordingSMTP.instances


def mailer(**overrides):
    """Build a mailer with plausible settings.

    Args:
        **overrides: Settings to replace.

    Returns:
        A configured ``SMTPMailer``.
    """
    settings = {
        "host": "smtp.example.com",
        "port": 587,
        "username": "",
        "password": "",
        "sender": "no-reply@example.com",
        "use_tls": True,
        "use_ssl": False,
        "timeout": 7.5,
        "logger": None,
    }
    settings.update(overrides)
    return SMTPMailer(**settings)


class TestTheMessageItBuilds:
    """The three headers and the body, as the recipient would see them."""

    def test_headers_and_body_reach_the_server(self, smtp):
        mailer().send("user@example.com", "Confirm", "Open the link")

        message = smtp[0].sent[0]
        assert message["From"] == "no-reply@example.com"
        assert message["To"] == "user@example.com"
        assert message["Subject"] == "Confirm"
        assert message.get_content() == "Open the link\n"

    def test_the_body_is_plain_text(self, smtp):
        """A confirmation mail that arrives as an attachment is not read."""
        mailer().send("user@example.com", "Confirm", "Open the link")

        assert smtp[0].sent[0].get_content_type() == "text/plain"

    def test_it_carries_no_headers_beyond_the_three(self, smtp):
        """Named exhaustively, because a header nobody asserts about is a
        header anybody can add. A ``Bcc`` inserted here would copy every
        confirmation link to a fourth party, be stripped from the message
        text by SMTP so no recipient sees it, and pass a suite that only
        checks that From, To and Subject are right."""
        mailer().send("user@example.com", "Confirm", "Open the link")

        headers = {
            name for name in smtp[0].sent[0].keys()
            if not name.lower().startswith("content-")
            and name.lower() != "mime-version"
        }
        assert headers == {"From", "To", "Subject"}

    def test_exactly_one_message_goes_out(self, smtp):
        """Duplicated confirmations read as a service under attack, to the
        user and to the receiving domain's reputation scoring alike."""
        mailer().send("user@example.com", "Confirm", "Open the link")

        assert len(smtp[0].sent) == 1

    def test_a_newline_in_the_recipient_is_refused(self, smtp):
        """The shape of a header injection, and it must not be delivered.

        ``EmailMessage`` raises rather than the mailer, which is the point:
        the refusal is not a rule this class remembers to apply. Asserted
        here anyway, because "somebody else checks it" is how a check
        disappears -- and because the connection must not have been opened.
        """
        with pytest.raises(ValueError):
            mailer().send(
                "user@example.com\r\nBcc: evil@example.com",
                "Confirm",
                "Open the link",
            )

        assert smtp == [], "a message that cannot be built must not connect"

    def test_a_newline_in_the_subject_is_refused(self, smtp):
        with pytest.raises(ValueError):
            mailer().send("user@example.com", "Hi\nBcc: evil@example.com", "text")

        assert smtp == []


class TestHowItReachesTheServer:
    """STARTTLS on 587, Implicit TLS on 465, and the timeout on both."""

    def test_starttls_is_negotiated_with_a_verifying_context(self, smtp):
        """Without a context the handshake verifies nothing at all."""
        mailer().send("user@example.com", "Confirm", "text")

        context = smtp[0].starttls_calls[0]
        assert isinstance(context, ssl.SSLContext)
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname is True

    def test_capabilities_are_re_read_after_the_handshake(self, smtp):
        """What a server advertised in the clear does not bind it."""
        mailer().send("user@example.com", "Confirm", "text")

        assert smtp[0].ehlo_calls == 1

    def test_implicit_tls_does_not_negotiate_starttls(self, smtp):
        """STARTTLS inside TLS is a protocol error, not extra safety."""
        mailer(use_tls=False, use_ssl=True, port=465).send(
            "user@example.com", "Confirm", "text"
        )

        assert isinstance(smtp[0], RecordingSMTPSSL)
        assert smtp[0].starttls_calls == []

    def test_implicit_tls_verifies_the_certificate_too(self, smtp):
        """The same assertion as for STARTTLS, and it was missing here.

        Checking only that *some* context was passed accepts one built
        with ``CERT_NONE``: measured against a TLS server presenting a
        self-signed certificate for another name, that variant handed over
        the password and the confirmation link, and the suite stayed
        green.
        """
        mailer(use_tls=False, use_ssl=True, port=465).send(
            "user@example.com", "Confirm", "text"
        )

        context = smtp[0].context
        assert isinstance(context, ssl.SSLContext)
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname is True

    def test_a_server_that_refuses_starttls_gets_no_message(self, smtp, monkeypatch):
        """A downgrade -- a server that does not offer STARTTLS, or an
        attacker stripping it from the greeting -- must end the attempt,
        not continue in the clear."""
        def refuse(self, context=None):
            raise smtplib.SMTPNotSupportedError(
                "STARTTLS extension not supported by server."
            )

        monkeypatch.setattr(RecordingSMTP, "starttls", refuse)

        with pytest.raises(MailDeliveryError):
            mailer().send("user@example.com", "Confirm", "text")

        assert smtp[0].sent == []

    def test_a_connection_that_fails_to_negotiate_is_released(
        self, smtp, monkeypatch
    ):
        """The socket is opened before anything owns it.

        Until it was released here, a refused negotiation left an open
        connection with no owner: measured at two descriptors per attempt
        for as long as the exception was held, and the server never saw a
        QUIT -- which submission providers treat as a reason to throttle.
        """
        def refuse(self, context=None):
            raise smtplib.SMTPNotSupportedError("no STARTTLS here")

        monkeypatch.setattr(RecordingSMTP, "starttls", refuse)

        with pytest.raises(MailDeliveryError):
            mailer().send("user@example.com", "Confirm", "text")

        assert smtp[0].quits + smtp[0].closes >= 1

    def test_plain_submission_negotiates_nothing(self, smtp):
        """What the local catcher gets: no TLS asked for, none attempted."""
        mailer(use_tls=False, use_ssl=False, port=1025).send(
            "user@example.com", "Confirm", "text"
        )

        assert smtp[0].starttls_calls == []
        assert not isinstance(smtp[0].sock, ssl.SSLSocket)

    @pytest.mark.parametrize(
        "settings", [{}, {"use_tls": False, "use_ssl": True}]
    )
    def test_the_timeout_is_passed_through(self, smtp, settings):
        """Left out, smtplib waits on the global default, which is never.

        Both branches are checked because they build their client
        separately, and the one that was missing it would only be found by
        a server that accepts a connection and then goes quiet.
        """
        mailer(**settings).send("user@example.com", "Confirm", "text")

        assert smtp[0].timeout == 7.5

    def test_the_connection_is_closed(self, smtp):
        mailer().send("user@example.com", "Confirm", "text")

        assert smtp[0].exited is True


class TestTheCredentials:
    """When the password is sent, and when it is withheld."""

    def test_no_username_means_no_login(self, smtp):
        mailer().send("user@example.com", "Confirm", "text")

        assert smtp[0].logins == []

    def test_a_username_authenticates_over_tls(self, smtp):
        mailer(username="postmaster", password="s3cret").send(
            "user@example.com", "Confirm", "text"
        )

        assert smtp[0].logins == [("postmaster", "s3cret")]

    def test_an_unencrypted_channel_gets_no_password(self, smtp):
        """A mailer built with no TLS at all must withhold the password.

        Reachable by construction rather than by any server behaviour:
        ``smtplib`` raises when a STARTTLS is unadvertised or refused, so
        a mailer that asked for TLS never arrives here with a plain
        socket. What does arrive is a mailer built outside the container,
        past the configuration check that would have refused it.
        """
        sender = mailer(username="postmaster", password="s3cret", use_tls=False)

        with pytest.raises(MailDeliveryError, match="unencrypted"):
            sender.send("user@example.com", "Confirm", "text")

        assert smtp[0].logins == []
        assert smtp[0].sent == [], "the message must not go out either"

    def test_the_check_reads_the_socket_and_not_the_setting(
        self, smtp, monkeypatch
    ):
        """``use_tls`` says what was asked for; the socket says what is.

        The case above cannot tell those apart -- it has both the setting
        off and the socket plain, so a check written as
        ``if not (self.use_tls or self.use_ssl)`` passes it. Here the
        setting says TLS and the negotiation leaves the socket plain,
        which only the socket-reading check catches. Contrived on purpose:
        it is a guard on the shape of the check, for the next person who
        rewrites it into something that trusts the configuration.
        """
        def negotiate_nothing(self, context=None):
            self.starttls_calls.append(context)

        monkeypatch.setattr(RecordingSMTP, "starttls", negotiate_nothing)
        sender = mailer(username="postmaster", password="s3cret", use_tls=True)

        with pytest.raises(MailDeliveryError, match="unencrypted"):
            sender.send("user@example.com", "Confirm", "text")

        assert smtp[0].logins == []
        assert smtp[0].sent == []


class TestWhatItDoesWithFailure:
    """Every way the network fails arrives as one named error."""

    @pytest.mark.parametrize(
        "failure",
        [
            ConnectionRefusedError("refused"),
            TimeoutError("timed out"),
            OSError("unreachable"),
            ssl.SSLError("certificate verify failed"),
            smtplib.SMTPAuthenticationError(535, b"bad credentials"),
            smtplib.SMTPRecipientsRefused({"user@example.com": (550, b"no")}),
            smtplib.SMTPServerDisconnected("hung up"),
        ],
    )
    def test_transport_failures_become_delivery_errors(
        self, smtp, monkeypatch, failure
    ):
        """Callers get one exception to handle, not seven.

        ``ssl.SSLError`` is in the list on purpose: it is an ``OSError``,
        so a rejected certificate lands in the same branch as an
        unreachable host rather than escaping uncaught.
        """
        def explode(self, message):
            raise failure

        monkeypatch.setattr(RecordingSMTP, "send_message", explode)

        with pytest.raises(MailDeliveryError):
            mailer().send("user@example.com", "Confirm", "text")

    def test_a_refused_connection_becomes_a_delivery_error(self, monkeypatch):
        """The failure that happens before there is any client at all."""
        def refuse(*args, **kwargs):
            raise ConnectionRefusedError("refused")

        monkeypatch.setattr(smtplib, "SMTP", refuse)

        with pytest.raises(MailDeliveryError, match="smtp.example.com:587"):
            mailer().send("user@example.com", "Confirm", "text")

    def test_the_failure_is_logged_with_the_server_it_was_talking_to(
        self, smtp, monkeypatch
    ):
        """An operator reading the log needs to know which host went dark."""
        def explode(self, message):
            raise OSError("unreachable")

        monkeypatch.setattr(RecordingSMTP, "send_message", explode)
        logger = Mock()

        with pytest.raises(MailDeliveryError):
            mailer(logger=logger).send("user@example.com", "Confirm", "text")

        _, kwargs = logger.error.call_args
        assert kwargs["host"] == "smtp.example.com"
        assert kwargs["port"] == 587

    def test_neither_the_body_nor_the_password_is_logged(self, smtp, monkeypatch):
        """The link is a credential, and so is the password beside it.

        Asserted over every call the logger received, not over
        ``logger.error`` alone. Reading one method's arguments leaves every
        other level unwatched: a ``logger.debug`` carrying the body passes
        such a check untouched, and DEBUG is the ordinary level in
        development.
        """
        def explode(self, message):
            raise OSError("unreachable")

        monkeypatch.setattr(RecordingSMTP, "send_message", explode)
        logger = Mock()

        with pytest.raises(MailDeliveryError):
            mailer(logger=logger, username="postmaster", password="s3cret").send(
                "user@example.com", "Confirm", "https://x.example/verify?t=SECRET"
            )

        everything_logged = str(logger.mock_calls)
        assert "SECRET" not in everything_logged
        assert "s3cret" not in everything_logged
