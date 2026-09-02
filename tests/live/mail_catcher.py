"""
A mail receiver on the loopback, for the live runs.

Both runs in this directory used to walk around the same joint. An account
was confirmed either by a direct `UPDATE users SET email_verified = 1` or
by a confirmation string the run made up itself and put into the table
itself. Both check `/api/v1/auth/verify` against a token issued by the test
rather than by the service: should registration stop issuing a token, or
the mail template build the link to the wrong place, both checks stay
green. One such scenario had already broken unnoticed.

Through this receiver runs exactly the path that runs in service:
registration issues a token, the template builds the link, ``SMTPMailer``
hands the message over by SMTP -- and the run takes the link out of the
delivered message and follows it. It also answers the question the old
detours never asked: does the mail go out at all.

There is exactly as much SMTP here as ``smtplib`` speaks: the greeting,
EHLO, the envelope, DATA, QUIT. Neither TLS nor authentication -- ``mailpit``,
which the development profile points at, offers neither either.
"""

import re
import socketserver
import threading
from email import message_from_string
from typing import List, Optional
from urllib.parse import urlsplit


class _Handler(socketserver.StreamRequestHandler):
    """One SMTP session."""

    def handle(self) -> None:
        """Talk one session through and put what arrives in the mailbox."""
        self._say("220 catcher ready")
        while True:
            line = self.rfile.readline()
            if not line:
                return
            command = line.decode("utf-8", "replace").strip()
            head = command.split()[0].upper() if command.split() else ""

            if head in ("EHLO", "HELO"):
                self._say("250 catcher")
            elif head in ("MAIL", "RCPT", "RSET", "NOOP"):
                self._say("250 ok")
            elif head == "DATA":
                self._say("354 end with a lone dot")
                self.server.mailbox.append(self._read_message())
                self._say("250 accepted")
            elif head == "QUIT":
                self._say("221 bye")
                return
            else:
                self._say("502 not implemented")

    def _say(self, text: str) -> None:
        """
        Answer with one line of the protocol.

        Args:
            text: The reply line, without its terminator.
        """
        self.wfile.write(text.encode("ascii") + b"\r\n")
        self.wfile.flush()

    def _read_message(self) -> str:
        """
        Read the message body up to a lone dot.

        Returns:
            The whole message, headers included, with dots at the start of a
            line restored.
        """
        lines: List[str] = []
        while True:
            raw = self.rfile.readline()
            if not raw:
                break
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line == ".":
                break
            lines.append(line[1:] if line.startswith("..") else line)
        return "\n".join(lines)


class _Server(socketserver.ThreadingTCPServer):
    """A TCP server with one mailbox shared by every session."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address):
        """
        Args:
            address: A (host, port) pair; port 0 means "any free one".
        """
        super().__init__(address, _Handler)
        self.mailbox: List[str] = []


class MailCatcher:
    """
    A mail server that sends nothing anywhere.

    It comes up on the loopback, on a port the kernel chooses, and lives in
    a thread of its own until the run stops it.

    Attributes:
        port: The port the receiver listens on.
    """

    def __init__(self) -> None:
        """Bring the receiver up and start accepting sessions."""
        self._server = _Server(("127.0.0.1", 0))
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the receiver and give the port back."""
        self._server.shutdown()
        self._server.server_close()

    def clear(self) -> None:
        """Throw away everything received, so the next check looks for its own."""
        self._server.mailbox.clear()

    def messages_to(self, address: str) -> List[str]:
        """
        Pick out the messages addressed to one recipient.

        Args:
            address: The address in the ``To`` field.

        Returns:
            The message bodies in order of delivery, already decoded.

            Decoding is not optional: ``EmailMessage.set_content`` chooses
            quoted-printable, and the confirmation link arrives in it and
            broken by a soft line break --
            ``token=3DAAAA...AAAA=\\nAAAA``. A mail client puts that back
            together; a run reading the raw body would take the stump and be
            answered "This confirmation link is not valid".
        """
        found = []
        for raw in self._server.mailbox:
            message = message_from_string(raw)
            if message.get("To", "") == address:
                payload = message.get_payload(decode=True)
                charset = message.get_content_charset() or "utf-8"
                found.append(payload.decode(charset))
        return found

    def confirmation_link(self, address: str) -> Optional[str]:
        """
        Take the confirmation link out of the last message to an address.

        The path is deliberately not named in the pattern: any address
        carrying a ``token`` parameter matches. Otherwise the pattern would
        repeat the very thing it is meant to check and would confirm a link
        built to the wrong place -- which is exactly how the first version
        of this change passed with a substituted ``VERIFY_PATH``.

        Args:
            address: The address the confirmation was sent to.

        Returns:
            The whole link, or ``None`` when there is no message or no link
            in it.
        """
        for body in reversed(self.messages_to(address)):
            match = re.search(r"https?://\S*\?\S*token=\S+", body)
            if match:
                return match.group(0).rstrip(".,)")
        return None

    def confirmation_target(self, address: str) -> Optional[str]:
        """
        The same link as a path and query alone -- how a test client takes it.

        Args:
            address: The address the confirmation was sent to.

        Returns:
            The path with its query string, or ``None``.
        """
        link = self.confirmation_link(address)
        if link is None:
            return None
        parts = urlsplit(link)
        return parts.path + (f"?{parts.query}" if parts.query else "")
