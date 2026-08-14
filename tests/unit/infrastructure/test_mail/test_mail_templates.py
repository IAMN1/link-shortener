"""The message a person actually receives, and where it comes from.

Rendered from files on disk, so two things can go wrong that no amount of
logic testing would catch: the files can fail to reach the installed
package, and the rendering can quietly corrupt the one thing the message
exists to carry.
"""

import tomllib
from pathlib import Path

import pytest

from link_shortener.infrastructure.mail.jinja_templates import (
    TEMPLATE_DIR,
    JinjaMailTemplates,
)


URL = "https://links.example.com/api/v1/auth/verify?token=AbC-123_xyz"


@pytest.fixture
def templates():
    """The real renderer, reading the real templates."""
    return JinjaMailTemplates()


class TestTheConfirmationMessage:
    """What it says, and what it must carry unchanged."""

    def test_the_link_survives_rendering(self, templates):
        """The one thing that must arrive byte for byte."""
        _, body = templates.verification_email(confirm_url=URL, ttl_hours=24)

        assert URL in body

    def test_nothing_is_html_escaped(self, templates):
        """Autoescaping in a text/plain body corrupts the link: an ``&``
        becomes ``&amp;`` and the URL stops matching its own token."""
        url = "https://x.example/api/v1/auth/verify?token=a&b='c'"

        _, body = templates.verification_email(confirm_url=url, ttl_hours=24)

        assert url in body
        assert "&amp;" not in body

    def test_it_says_how_long_the_link_lives(self, templates):
        """A link with no stated lifetime is one people come back to a
        week later."""
        _, body = templates.verification_email(confirm_url=URL, ttl_hours=6)

        assert "6 hour" in body

    def test_one_hour_reads_as_one_hour(self, templates):
        _, body = templates.verification_email(confirm_url=URL, ttl_hours=1)

        assert "1 hour." in body
        assert "1 hours" not in body

    def test_the_subject_carries_no_line_break(self, templates):
        """A header cannot hold one: ``EmailMessage`` refuses the whole
        message, and that refusal would surface as a failed registration
        rather than as the template mistake it is."""
        subject, _ = templates.verification_email(confirm_url=URL, ttl_hours=24)

        assert "\n" not in subject
        assert "\r" not in subject
        assert subject

    def test_the_message_is_sendable(self, templates):
        """Assembled for real, because the refusal above is the stdlib's
        and only shows up when a message is actually built."""
        from email.message import EmailMessage

        subject, body = templates.verification_email(
            confirm_url=URL, ttl_hours=24
        )
        message = EmailMessage()
        message["Subject"] = subject
        message.set_content(body)

        assert message["Subject"] == subject

    def test_a_missing_variable_is_an_error_and_not_a_blank(self, templates):
        """Undefined renders as an empty string by default, which here
        means mailing somebody a message with nothing where the link
        should be."""
        from jinja2 import UndefinedError

        with pytest.raises(UndefinedError):
            templates.environment.get_template("verification_body.txt").render()


class TestTheAccountExistsMessage:
    """Sent to an address somebody tried to register a second time."""

    SIGN_IN = "https://links.example.com/login"

    def test_it_points_at_the_sign_in_page(self, templates):
        _, body = templates.account_exists_email(sign_in_url=self.SIGN_IN)

        assert self.SIGN_IN in body

    def test_it_carries_nothing_that_grants_anything(self, templates):
        """Sent to an address the caller may not own, and triggered by
        anyone who can type it. A confirmation link in here would be a
        credential handed out on request."""
        _, body = templates.account_exists_email(sign_in_url=self.SIGN_IN)

        assert "token" not in body.lower()
        assert "/auth/verify" not in body

    def test_the_subject_carries_no_line_break(self, templates):
        subject, _ = templates.account_exists_email(sign_in_url=self.SIGN_IN)

        assert "\n" not in subject
        assert "\r" not in subject
        assert subject

    def test_the_message_is_sendable(self, templates):
        from email.message import EmailMessage

        subject, body = templates.account_exists_email(
            sign_in_url=self.SIGN_IN
        )
        message = EmailMessage()
        message["Subject"] = subject
        message.set_content(body)

        assert message["Subject"] == subject

    def test_a_missing_variable_is_an_error_and_not_a_blank(self, templates):
        from jinja2 import UndefinedError

        with pytest.raises(UndefinedError):
            templates.environment.get_template("account_exists_body.txt").render()


class TestTheTemplatesReachTheImage:
    """Files that stay in the repository are files production does not have."""

    def test_every_template_is_declared_as_package_data(self):
        """``roles.yaml`` was left behind exactly this way once, and the
        failure was invisible until a command ran in the built image.

        Matched against the patterns in ``pyproject.toml`` rather than
        against a list repeated here, so adding a template with a new
        extension fails this instead of failing in production.
        """
        root = Path(__file__).resolve().parents[4]
        patterns = tomllib.loads((root / "pyproject.toml").read_text())[
            "tool"
        ]["setuptools"]["package-data"]["link_shortener"]

        package = root / "src" / "link_shortener"
        templates = [
            p for p in (package / "web" / "templates").rglob("*") if p.is_file()
        ]
        assert templates, "no templates found at all"

        for template in templates:
            relative = template.relative_to(package)
            assert any(
                relative.match(pattern) for pattern in patterns
            ), f"{relative} would not be installed into the package"

    def test_the_message_templates_are_where_the_renderer_looks(self):
        assert (TEMPLATE_DIR / "verification_subject.txt").is_file()
        assert (TEMPLATE_DIR / "verification_body.txt").is_file()
        assert (TEMPLATE_DIR / "account_exists_subject.txt").is_file()
        assert (TEMPLATE_DIR / "account_exists_body.txt").is_file()

    def test_the_renderer_finds_them_inside_the_package(self):
        """Counted inside the package, not up to a project root: the image
        installs the package into ``site-packages``, where no project root
        exists and counting levels lands in ``/usr/local/lib``."""
        package = Path(
            __import__("link_shortener").__file__
        ).resolve().parent

        assert TEMPLATE_DIR.is_relative_to(package)
