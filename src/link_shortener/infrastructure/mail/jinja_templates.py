from pathlib import Path
from typing import Tuple

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from link_shortener.application.ports.mail_templates import MailTemplates


TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "web" / "templates" / "email"
"""Where the message templates live.

Counted inside the package rather than up to a project root, and the
difference matters: the image installs the package into ``site-packages``
and the project tree is not there at all. This walk only ever crosses
directories the package itself owns, so it resolves the same in both
places -- provided the files are shipped, which is what the
``web/templates/**/*.txt`` line in ``pyproject.toml`` is for.
"""


class JinjaMailTemplates(MailTemplates):
    """
    Renders outgoing messages from templates on disk.

    Plain text, and the environment says so by leaving autoescaping off.
    Turning it on would be the safe-looking choice and the wrong one here:
    HTML escaping inside a text/plain body corrupts the very thing the
    message exists to carry, turning an ``&`` in a URL into ``&amp;`` and
    an apostrophe into ``&#39;``.

    Attributes:
        environment: The Jinja environment loading from ``TEMPLATE_DIR``.
    """

    def __init__(self, template_dir: Path = TEMPLATE_DIR):
        """
        Args:
            template_dir: Directory holding the message templates.
        """
        self.environment = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=False,
            # A missing variable renders as an empty string by default,
            # which for these templates means mailing somebody a message
            # with a blank where the link should be. Raising instead turns
            # that into a failure the logs can show.
            undefined=StrictUndefined,
            keep_trailing_newline=True,
        )

    def verification_email(self, confirm_url: str, ttl_hours: int) -> Tuple[str, str]:
        """
        Render the message that carries a confirmation link.

        Args:
            confirm_url: Absolute URL that confirms the address.
            ttl_hours: How long that URL stays usable.

        Returns:
            Tuple of (subject, body), both plain text. The subject is
            stripped of its trailing newline, because a header cannot
            carry one -- ``EmailMessage`` refuses the whole message if it
            does, and that refusal would arrive as a failed registration
            rather than as the template mistake it is.
        """
        subject = self.environment.get_template("verification_subject.txt").render()
        body = self.environment.get_template("verification_body.txt").render(
            confirm_url=confirm_url, ttl_hours=ttl_hours
        )
        return subject.strip(), body
