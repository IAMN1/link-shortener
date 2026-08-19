"""Where the guest allowance is said, and to whom.

The limit and the lifetime that apply to links made without an account are
a guest's business. They are read from ``GUEST_LINK_LIMIT`` and
``DEFAULT_GUEST_TTL_SECONDS`` and shown on the landing page under
``{% if not g.current_user %}`` -- ``frontend_controller.index`` states the
rule in its own docstring: "a deployment that changes them changes what the
page says".

The dashboard's create-link form carried a second copy of half of it: "Links
made without an account expire after 7 days", written into the markup as the
number seven, on a page nobody reaches without signing in. It answered a
question its reader had not asked, with a figure a deployment could change
underneath it, two centimetres below the control that actually sets the
lifetime of the link being made.
"""

from pathlib import Path
from unittest.mock import Mock

import pytest
from flask import g, render_template


TEMPLATES = (
    Path(__file__).resolve().parents[4]
    / "src" / "link_shortener" / "web" / "templates"
)


@pytest.fixture
def signed_in(app):
    """Render the dashboard as somebody who is signed in."""
    user = Mock()
    user.id = "11111111-1111-1111-1111-111111111111"
    user.email = "someone@example.com"
    user.roles = ["admin"]

    allows_everything = Mock()
    allows_everything.is_allowed.return_value = True

    with app.test_request_context("/dashboard/create-link"):
        g.current_user = user
        g.authorization_service = allows_everything
        yield


class TestTheDashboardDoesNotQuoteTheGuestPolicy:

    def test_the_form_says_nothing_about_accountless_links(self, signed_in):
        markup = render_template("dashboard/create_link.html")

        assert "without an account" not in markup

    def test_no_lifetime_is_written_into_the_markup_as_a_sentence(self):
        """
        The number, not just the sentence around it.

        A hint reading "expire after 7 days" is wrong the day
        ``DEFAULT_GUEST_TTL_SECONDS`` changes, and nothing would say so:
        the page renders, the form works, and the sentence quietly
        describes a policy the service no longer has.
        """
        source = (TEMPLATES / "dashboard" / "create_link.html").read_text()

        assert "expire after" not in source


class TestTheLandingPageStillTellsAGuest:
    """
    The other half of the same rule: removed from one page, still said on
    the page whose reader it is about, and still said with the numbers the
    configuration holds rather than numbers typed into the markup.
    """

    def test_the_allowance_is_shown_to_visitors_who_are_not_signed_in(self):
        source = (TEMPLATES / "public" / "index.html").read_text()

        assert "{% if not g.current_user and guest_link_limit %}" in source
        assert "expires after" in source

    def test_both_figures_come_from_the_view_and_not_from_the_markup(self):
        """
        ``frontend_controller.index`` reads them from the configuration
        and passes them in, "so a deployment that changes them changes
        what the page says". The template has to be asking for them.
        """
        source = (TEMPLATES / "public" / "index.html").read_text()

        assert "{{ guest_link_limit }}" in source
        assert "{{ guest_ttl_days }}" in source
