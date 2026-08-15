"""
Tests that the sidebar is rendered in the state the last visit left it.

The collapsed rail is a preference, so it has to survive a page load. It
survives as a cookie the server reads while rendering rather than as a
value a script applies afterwards: applied afterwards, every page draws
the full sidebar first and snaps it shut once the script runs.

That is what these tests hold. They render the template with and without
the cookie, because the defect they guard against -- the markup ignoring
the cookie -- leaves a page that works, looks right for a moment, and
flickers on every navigation. Nothing fails and nothing is logged.

``tests/live/browser_test.py`` covers the other half in a real browser:
that pressing the control writes the cookie, and that the next page comes
back narrow.
"""

from unittest.mock import Mock

import pytest
from flask import g, render_template


@pytest.fixture
def signed_in(app):
    """
    Render as an admin, the way the sidebar's own tests do.

    ``g.authorization_service`` is set by hand because
    ``test_request_context`` runs no middleware and every menu entry asks
    that service whether the caller may go there.
    """
    user = Mock()
    user.id = "11111111-1111-1111-1111-111111111111"
    user.email = "someone@example.com"
    user.roles = ["admin"]

    allows_everything = Mock()
    allows_everything.is_allowed.return_value = True

    def render(cookies=None):
        with app.test_request_context("/dashboard/", headers=cookies or {}):
            g.current_user = user
            g.authorization_service = allows_everything
            return render_template("dashboard/home.html")

    return render


COLLAPSED = {"Cookie": "dash_sidebar=rail"}


class TestTheSidebarIsDrawnInTheRememberedState:

    def test_it_is_open_when_nothing_was_remembered(self, signed_in):
        markup = signed_in()

        assert "dash--rail" not in markup
        assert 'aria-expanded="true"' in markup

    def test_the_cookie_collapses_it_before_the_page_is_sent(self, signed_in):
        markup = signed_in(COLLAPSED)

        assert "dash--rail" in markup
        # The class is what the eye reads and this is what a screen reader
        # reads; a page that says one and not the other is telling two
        # different stories about the same menu.
        assert 'aria-expanded="false"' in markup

    def test_a_value_the_service_never_writes_leaves_it_open(self, signed_in):
        """
        A cookie is client-side, so its value is whatever anyone typed.

        Only ``rail`` collapses. Anything else -- a stale value, a hand-
        edited one -- has to land on the state a first-time visitor gets
        rather than on an unstyled half-width menu.
        """
        markup = signed_in({"Cookie": "dash_sidebar=<script>"})

        assert "dash--rail" not in markup
        assert 'aria-expanded="true"' in markup

    def test_the_collapsed_menu_keeps_the_names_of_its_entries(self, signed_in):
        """
        The labels are hidden by the stylesheet, not dropped from the page.

        Dropping them is the tempting way to draw a 56px rail, and it costs
        a screen reader every menu entry's name: what is left is nine links
        that announce themselves as nothing at all.
        """
        markup = signed_in(COLLAPSED)

        for name in ("My Links", "Create Link", "Service Stats", "Users",
                     "Roles", "Health Check", "Logout"):
            assert name in markup, f"the rail dropped {name!r} from the markup"
