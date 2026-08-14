"""
Tests that every dashboard page loads the script the dashboard runs on.

``dashboard.js`` binds the sidebar toggle and the sidebar's logout button.
It was included from ``dashboard/base.html`` inside ``{% block scripts %}``
-- the same block each page overrides to add its own script, and an override
replaces what it overrides. Included that way the file reaches two pages
out of twelve; on the other ten both controls are dead. Nothing fails and
nothing is logged: the page renders, the button
is drawn, and it does nothing when pressed.

Rendered here rather than fetched, because the defect is in template
inheritance and a rendering needs neither an account nor a database. The
integration app is used because it is the one with the real templates.
"""

from unittest.mock import Mock

import pytest
from flask import g, render_template


DASHBOARD_JS = "js/dashboard.js"

PAGES = [
    ("dashboard/home.html", {}),
    ("dashboard/my_links.html", {"user": None}),
    ("dashboard/my_stats.html", {}),
    ("dashboard/create_link.html", {}),
    ("dashboard/service_stats.html", {}),
    ("dashboard/health.html", {}),
    ("dashboard/user_stats.html", {"user": None}),
    ("dashboard/users_list.html", {"users": []}),
    ("dashboard/create_user.html", {"roles": []}),
    ("dashboard/edit_user.html", {"user": None, "all_roles": []}),
    ("dashboard/roles_list.html", {"roles": []}),
    ("dashboard/create_role.html", {"permissions": []}),
]
"""Every page the dashboard serves, with whatever its view passes it."""


@pytest.fixture
def signed_in(app):
    """Render as an admin: the sidebar draws its full set of links."""
    user = Mock()
    user.email = "someone@example.com"
    user.roles = ["admin"]

    with app.test_request_context("/dashboard/"):
        g.current_user = user
        yield


class TestEveryDashboardPageLoadsTheDashboardScript:

    @pytest.mark.parametrize("template,context", PAGES)
    def test_the_shared_script_is_present(self, signed_in, template, context):
        markup = render_template(template, **context)

        assert DASHBOARD_JS in markup, f"{template} renders without dashboard.js"

    def test_a_pages_own_script_is_still_loaded(self, signed_in):
        """Added, not swapped in: the page keeps its own script as well."""
        markup = render_template("dashboard/create_link.html")

        assert DASHBOARD_JS in markup
        assert "js/pages/create_link.js" in markup

    def test_the_controls_the_script_binds_are_on_the_page(self, signed_in):
        """Otherwise the assertion above would pass over a dead control."""
        markup = render_template("dashboard/my_stats.html")

        assert 'id="logout-btn"' in markup
        assert 'id="dash-toggle"' in markup
