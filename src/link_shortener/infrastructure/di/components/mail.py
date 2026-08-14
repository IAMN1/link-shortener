from typing import Optional
from link_shortener.application import Mailer
from link_shortener.infrastructure.mail.null_mailer import NullMailer
from link_shortener.infrastructure.mail.smtp_mailer import SMTPMailer


class MailComponent:
    """
    Provides a singleton ``Mailer`` implementation.

    When the mail channel is enabled, messages are submitted over SMTP;
    otherwise they are accepted and dropped, which keeps a deployment
    without mail serving links.
    """

    def __init__(
        self,
        mail_enabled: bool,
        host: str,
        port: int,
        username: str,
        password: str,
        sender: str,
        use_tls: bool,
        use_ssl: bool,
        timeout: float,
        logger,
    ):
        """
        Args:
            mail_enabled: If True, submit over SMTP.
            host: Submission server hostname.
            port: Submission port.
            username: Account to authenticate as, or empty for none.
            password: Password for that account.
            sender: Address the service sends from.
            use_tls: Negotiate STARTTLS after connecting.
            use_ssl: Connect with TLS already established.
            timeout: Seconds any single socket operation may take.
            logger: Application logger for diagnostics.
        """
        self.mail_enabled = mail_enabled
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender = sender
        self.use_tls = use_tls
        self.use_ssl = use_ssl
        self.timeout = timeout
        self.logger = logger
        # Annotated Optional rather than inferred from this assignment: the
        # attribute holds None until the first call builds it, and a checker
        # told otherwise reports both the assignment and the return as errors.
        self._mailer: Optional[Mailer] = None

    def get_mailer(self) -> Mailer:
        """
        Return the configured mailer.

        Returns:
            ``SMTPMailer`` or ``NullMailer``.
        """
        if self._mailer is None:
            if self.mail_enabled:
                self._mailer = SMTPMailer(
                    host=self.host,
                    port=self.port,
                    username=self.username,
                    password=self.password,
                    sender=self.sender,
                    use_tls=self.use_tls,
                    use_ssl=self.use_ssl,
                    timeout=self.timeout,
                    logger=self.logger,
                )
            else:
                self.logger.info("Mail disabled, using NullMailer")
                self._mailer = NullMailer(logger=self.logger)
        return self._mailer
