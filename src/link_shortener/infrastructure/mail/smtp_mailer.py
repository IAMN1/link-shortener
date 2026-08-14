import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional, Union

from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.mailer import Mailer, MailDeliveryError


class SMTPMailer(Mailer):
    """
    Sends mail by talking SMTP to a submission server.

    Built on ``smtplib`` and ``email.message`` from the standard library,
    so the mail channel adds no dependency to the runtime image.

    Two ways to reach the server, per RFC 8314 section 3.3: STARTTLS on
    port 587 and Implicit TLS on port 465, which the RFC calls equivalent
    provided both ends require TLS before submission.

    This class keeps the half of that which concerns credentials: the
    password is withheld unless the socket is encrypted. The other half --
    requiring TLS for the submission itself -- is the configuration's,
    through ``REQUIRE_MAIL_TLS``, enforced on the deployed profiles only.
    Development aims at a catcher on the loopback that speaks no TLS.

    Attributes:
        host: Submission server hostname.
        port: Submission port.
        username: Account to authenticate as, or empty for no auth.
        password: Password for that account.
        sender: Address the message is sent from.
        use_tls: Negotiate STARTTLS after connecting (port 587).
        use_ssl: Connect with TLS already in place (port 465).
        timeout: Seconds any single blocking socket operation may take.
        logger: Application logger, used to record a refused delivery.
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        sender: str,
        use_tls: bool,
        use_ssl: bool,
        timeout: float,
        logger: Optional[Logger] = None,
    ):
        """
        Args:
            host: Submission server hostname.
            port: Submission port.
            username: Account to authenticate as; empty disables the login
                step, which is what a local relay wants.
            password: Password for that account.
            sender: Address the message is sent from.
            use_tls: Negotiate STARTTLS after connecting.
            use_ssl: Connect with TLS already in place.
            timeout: Seconds any single blocking socket operation may take.
            logger: Application logger for diagnostics.
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender = sender
        self.use_tls = use_tls
        self.use_ssl = use_ssl
        self.timeout = timeout
        self.logger = logger

    def send(self, to: str, subject: str, body: str) -> None:
        """
        Deliver one message to the submission server.

        Args:
            to: Recipient address.
            subject: Subject line, plain text.
            body: Message body, plain text.

        Raises:
            MailDeliveryError: If the server could not be reached, refused
                the message, or offered no encrypted channel to
                authenticate over.
            ValueError: If a header value carries a line break. Raised by
                ``EmailMessage`` and deliberately not translated: a
                delivery error says the network failed, while this says a
                newline reached a header, which is how a header injection
                is spelled. The two must not read alike in the logs.
        """
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        try:
            with self._connect() as smtp:
                if self.username:
                    self._require_encrypted(smtp)
                    smtp.login(self.username, self.password)
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException) as e:
            # OSError alone would do: smtplib.SMTPException derives from
            # it, as does ssl.SSLError, so a refused connection, a
            # rejected certificate and a server that answers 550 all land
            # here through the first name. The second is written out
            # anyway, because the inheritance is surprising enough that a
            # later reader narrowing this to SMTPException would think
            # they were keeping the mail failures and lose the network
            # ones instead.
            if self.logger:
                self.logger.error(
                    "Mail delivery failed",
                    error=str(e),
                    host=self.host,
                    port=self.port,
                )
            raise MailDeliveryError(
                f"could not deliver mail via {self.host}:{self.port}: {e}"
            ) from e

    def _connect(self) -> Union[smtplib.SMTP, smtplib.SMTP_SSL]:
        """
        Open the connection the configuration asks for.

        ``timeout`` is passed in both branches and is not optional: left
        out, ``smtplib`` falls back to the global default socket timeout,
        which is ``None`` unless something else in the process changed it.
        A submission server that accepts the connection and then stops
        answering would hold the caller forever.

        Returns:
            A connected SMTP client, with TLS in place when configured.
        """
        if self.use_ssl:
            return smtplib.SMTP_SSL(
                self.host,
                self.port,
                timeout=self.timeout,
                context=ssl.create_default_context(),
            )

        smtp = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
        try:
            if self.use_tls:
                # create_default_context() is what makes this a check
                # rather than a formality: it verifies the certificate
                # chain and the hostname. Without it an attacker in the
                # path answers the STARTTLS and reads everything that
                # follows, including the password below.
                smtp.starttls(context=ssl.create_default_context())
                # The server's capabilities are re-read after the
                # handshake, because what it advertised in the clear does
                # not bind it -- AUTH in particular is commonly offered
                # only once encrypted.
                smtp.ehlo()
        except BaseException:
            # Nothing owns this connection yet: the ``with`` in ``send``
            # only takes charge of what this method returns, so an
            # exception raised here left an open socket with no owner.
            # On a server that offers no STARTTLS: forty refused
            # sends leaked eighty descriptors for as long as the
            # exceptions were held, and the server saw no QUIT at all --
            # submission providers read abrupt disconnects as a reason to
            # throttle a sender.
            self._discard(smtp)
            raise

        return smtp

    @staticmethod
    def _discard(smtp: smtplib.SMTP) -> None:
        """
        Let go of a connection that will not be used.

        Args:
            smtp: The connection to release.
        """
        try:
            smtp.quit()
        except (OSError, smtplib.SMTPException):
            # A session that failed mid-negotiation may not be in a state
            # to be said goodbye to. The socket still has to go.
            smtp.close()

    def _require_encrypted(self, smtp: smtplib.SMTP) -> None:
        """
        Refuse to send the password over a channel that is not encrypted.

        Asks the socket rather than the configuration: ``use_tls`` says
        what was intended and the socket says what happened. A server
        refusing STARTTLS never reaches here -- ``smtplib`` raises before
        that -- so what this catches is a mailer built with both flags off
        outside the DI container.

        Args:
            smtp: The connected client, after any TLS negotiation.

        Raises:
            MailDeliveryError: If the connection is not encrypted.
        """
        if not isinstance(smtp.sock, ssl.SSLSocket):
            raise MailDeliveryError(
                f"refusing to authenticate to {self.host}:{self.port} over "
                "an unencrypted connection -- enable MAIL_USE_TLS or "
                "MAIL_USE_SSL"
            )
