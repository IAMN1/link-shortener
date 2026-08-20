"""
Tests that every dashboard page loads the script the dashboard runs on,
and loads it from the head.

``dashboard.js`` binds the sidebar toggle and the sidebar's logout button.
It was once included from ``dashboard/base.html`` inside
``{% block scripts %}`` -- the same block each page overrides to add its own
script, and an override replaces what it overrides. Included that way the
file reached two pages out of twelve; on the other ten both controls were
dead. Nothing failed and nothing was logged: the page rendered, the button
was drawn, and it did nothing when pressed.

It now loads from ``{% block extra_head %}``, which is why *where* is
checked as well as *whether*. Navigation is Turbo's: it swaps the ``<body>``
and merges the ``<head>``, skipping a script it already has. The file binds
its listeners to ``document``, which survives the swap. From the head it
therefore runs once per tab; moved back to the end of the body it would run
again on every navigation and leave another copy of every handler behind --
and the assertion that it is merely *present* would stay green through all
of it, since the tag is present either way. That is the failure this file
exists to make loud.

Rendered here rather than fetched, because the defect is in template
inheritance and a rendering needs neither an account nor a database. The
integration app is used because it is the one with the real templates.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import g, render_template


DASHBOARD_JS = "js/dashboard.js"

PAGES = [
    ("dashboard/home.html", {}),
    ("dashboard/my_links.html", {"user": None}),
    ("dashboard/my_stats.html", {}),
    # The code is what the view passes; it names the page and is carried
    # into the charts' requests.
    ("dashboard/link_stats.html", {"short_code": "abc123"}),
    ("dashboard/create_link.html", {}),
    ("dashboard/security.html", {}),
    ("dashboard/service_stats.html", {}),
    ("dashboard/health.html", {}),
    ("dashboard/journals.html", {}),
    ("dashboard/user_stats.html", {"user": None}),
    # `page` and `has_next` are what the view passes for the pager.
    ("dashboard/users_list.html", {"users": [], "page": 1, "has_next": False}),
    ("dashboard/create_user.html", {"roles": []}),
    ("dashboard/edit_user.html", {"user": None, "all_roles": []}),
    ("dashboard/roles_list.html", {"roles": []}),
    ("dashboard/create_role.html", {"permissions": []}),
    # `role` is a real object rather than a Mock: the template reads
    # `role.permissions|map(attribute='name')`, and a Mock answers that
    # with something Jinja cannot iterate.
    ("dashboard/edit_role.html",
     {"role": SimpleNamespace(name="editor", permissions=[]),
      "available_permissions": []}),
]
"""Every page the dashboard serves, with whatever its view passes it.

Held to that claim by ``test_this_list_names_every_dashboard_page`` below,
which finds the templates on disk rather than trusting this list. It was
written by hand and was wrong: ``edit_role.html`` was missing, so the page
went unchecked by every test parametrised over it.
"""


@pytest.fixture
def signed_in(app):
    """
    Render as an admin: the sidebar draws its full set of links.

    ``g.authorization_service`` is put in place by hand because
    ``test_request_context`` runs no middleware, and the markup asks that
    service what the caller may do. Without it every ``can(...)`` answered
    ``False``, so the sidebar rendered empty and this fixture's own
    description was untrue -- the pages were checked for a script tag with
    every menu entry missing.
    """
    user = Mock()
    user.id = "11111111-1111-1111-1111-111111111111"
    user.email = "someone@example.com"
    user.roles = ["admin"]

    allows_everything = Mock()
    allows_everything.is_allowed.return_value = True

    with app.test_request_context("/dashboard/"):
        g.current_user = user
        g.authorization_service = allows_everything
        yield


class TestTheListOfPagesIsTheListOfPages:

    def test_this_list_names_every_dashboard_page(self):
        """
        Every check in this file is parametrised over ``PAGES``, so a page
        missing from it is a page nothing here looks at -- and the file
        goes on reporting twelve green cases either way. That is how
        ``edit_role.html`` stayed unchecked.

        Found on disk instead: templates under ``dashboard/`` that are
        pages, which means the ones that extend the dashboard layout.
        Partials do not, and are excluded by exactly that.
        """
        directory = (
            Path(__file__).resolve().parents[4]
            / "src" / "link_shortener" / "web" / "templates" / "dashboard"
        )
        on_disk = {
            f"dashboard/{path.name}"
            for path in directory.glob("*.html")
            if 'extends "dashboard/base.html"' in path.read_text()
        }
        listed = {template for template, _ in PAGES}

        assert on_disk == listed, (
            f"dashboard pages missing from PAGES: {sorted(on_disk - listed)}; "
            f"listed but not on disk: {sorted(listed - on_disk)}"
        )


class TestEveryDashboardPageLoadsTheDashboardScript:

    @pytest.mark.parametrize("template,context", PAGES)
    def test_the_shared_script_is_present(self, signed_in, template, context):
        markup = render_template(template, **context)

        assert DASHBOARD_JS in markup, f"{template} renders without dashboard.js"

    @pytest.mark.parametrize("template,context", PAGES)
    def test_the_shared_script_is_in_the_head(self, signed_in, template,
                                              context):
        """
        Where it is loaded from decides how often it runs, and how often it
        runs decides whether its handlers accumulate. See this file's
        opening note.
        """
        head = render_template(template, **context).split("</head>")[0]

        assert DASHBOARD_JS in head, (
            f"{template} loads dashboard.js outside <head>: it will be "
            f"re-executed on every Turbo navigation and bind its listeners "
            f"to `document` again each time"
        )

    @pytest.mark.parametrize("template,context", PAGES)
    def test_the_navigation_library_is_in_the_head_too(self, signed_in,
                                                       template, context):
        """
        Same reason, one layer up: `main.js` binds to `document` as well,
        and Turbo has to be in the head or there is no navigation to speak
        of. Checked on the dashboard pages because these are the ones that
        inherit two layouts, where a block override can drop it.
        """
        head = render_template(template, **context).split("</head>")[0]

        assert "js/main.js" in head, f"{template} loads main.js outside <head>"
        assert "vendor/turbo-" in head, f"{template} renders without Turbo"

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

    def test_the_sidebar_this_fixture_describes_is_actually_drawn(self, signed_in):
        """
        Holds the fixture to its word.

        Every entry is behind a permission check, so a fixture that leaves
        the authorization service unset renders an empty rail and the
        checks above go on passing over a menu nobody would see.
        """
        markup = render_template("dashboard/home.html")

        for entry in ("My Links", "Create Link", "My Stats", "Service Stats",
                      "Users", "Roles", "Health Check"):
            assert entry in markup, f"the sidebar is missing {entry}"
