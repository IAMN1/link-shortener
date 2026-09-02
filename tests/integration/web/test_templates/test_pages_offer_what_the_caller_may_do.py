"""
What each page shows, measured against what the caller is allowed to do.

Two kinds of defect live here, and neither could fail a test before.

The first is a page that reads a value of the wrong shape. Nothing raises:
Jinja prints Undefined as an empty string, so ``{{ role.name }}`` over a
list of role *names* rendered a blank cell, and
``user.roles|map(attribute='name')`` matched nothing, so the form for
editing an account's roles opened with every box clear whatever the
account held. Both were on the administrator's own screens, and the whole
Python suite was green through both. Every page here is therefore rendered
from what its view really passes -- a registered account, its real roles,
the real role list -- and asserted on what a person would read.

The second is markup that decides by role name while the server decides by
permission. An analyst holds ``link:view_own`` and not ``link:create``, so
it was shown "Create Link" in two menus and on two pages, and every one of
them answered 403. A plain user holds ``stats:view_basic`` and was shown no
way to reach the page that serves it. The checks below pin each control to
the permission its endpoint asks for, so the two cannot drift apart again.
"""

import pytest
from sqlalchemy import text

from tests.integration.conftest import (
    account_with_permissions, csrf_headers, only_this_role,
)


@pytest.fixture(scope="module")
def operator(app):
    """An account that may look at users and roles, and change both."""
    return account_with_permissions(
        app,
        "pages-operator@example.com",
        "Test1234!",
        "pages-operator",
        [
            "admin:view_users",
            "admin:manage_users",
            "admin:view_roles",
            "admin:manage_roles",
            "link:view_own",
            "link:delete_own",
        ],
    )


@pytest.fixture(scope="module")
def reader(app):
    """An account that may read its own links and not create any."""
    account = account_with_permissions(
        app,
        "pages-reader@example.com",
        "Test1234!",
        "pages-reader",
        ["link:view_own", "stats:view_basic"],
    )
    only_this_role(app, account[2], "pages-reader")
    return account


@pytest.fixture(scope="module")
def any_links_analyst(app):
    """An account entitled to any link's traffic, not only to its own."""
    account = account_with_permissions(
        app,
        "pages-analyst@example.com",
        "Test1234!",
        "pages-analyst",
        [
            "link:view_own",
            "stats:view_basic",
            "stats:view_full",
            "stats:view_any",
        ],
    )
    only_this_role(app, account[2], "pages-analyst")
    return account


def page(client, path):
    """Fetch a page and hand back its markup."""
    response = client.get(path)
    assert response.status_code == 200, f"{path} answered {response.status_code}"
    return response.get_data(as_text=True)


def user_row(client, email, limit=40):
    """
    Find one account's row in the user list, paging until it turns up.

    The list is paginated, and a suite that has registered a few hundred
    accounts puts any particular one well past the first page -- so a
    check that reads page one alone fails for a reason that has nothing
    to do with what it is about. Paging here also means these checks
    exercise the pager itself.

    Args:
        client: A signed-in client entitled to see the list.
        email: Address of the account to find.
        limit: How many pages to look through before giving up.

    Returns:
        The markup of the page the account was found on.
    """
    for number in range(1, limit + 1):
        markup = page(client, f"/dashboard/users?page={number}")
        if f'data-user-email="{email}"' in markup:
            return markup
        if "Next &rarr;" not in markup and "Next →" not in markup:
            break
    raise AssertionError(f"{email} is on no page of the user list")


def emails_on(markup):
    """Addresses of the accounts a rendering of the list shows."""
    return {
        chunk.split('"')[0]
        for chunk in markup.split('data-user-email="')[1:]
    }


def register_enough_accounts(app, client):
    """
    Make sure more accounts exist than one page holds.

    Written against the page size rather than a number typed here: the
    two would drift, and a pager test that fits on one page passes
    without a pager.

    Args:
        app: The application under test.
        client: A client entitled to read the list.
    """
    from link_shortener.web.controllers.dashboard_controller import USERS_PER_PAGE

    with app.app_context():
        with app.container.get_db_manager().session() as session:
            existing = session.execute(
                text("SELECT COUNT(*) FROM users")
            ).fetchone()[0]
            for number in range(existing, USERS_PER_PAGE + 2):
                session.execute(
                    text(
                        "INSERT INTO users (id, email, password_hash, is_active, "
                        "email_verified, created_at) VALUES "
                        "(:id, :email, 'x', 1, 1, CURRENT_TIMESTAMP)"
                    ),
                    {
                        "id": f"pager-{number}",
                        "email": f"pager-{number}@example.com",
                    },
                )
            session.commit()


class TestTheUserListShowsWhatItHolds:

    def test_an_accounts_roles_are_named_in_the_table(self, operator):
        """
        The column was blank for every account in the service.

        Blank, not wrong: reading ``.name`` off a string is Undefined, and
        Undefined prints as nothing. An operator could not see who held
        what from the page whose job is to say so.
        """
        client, _, _ = operator

        markup = user_row(client, "pages-operator@example.com")

        # The badge specifically. Searching the page for the role name
        # passed on the account's own address -- "pages-operator" is a
        # substring of "pages-operator@example.com" -- so the check went
        # on passing with the column blank, which is the defect itself.
        #
        # `badge--name` was `badge--blue`, which set no blue: the rule gave
        # a grey border and ordinary text, and roles, permissions and states
        # all wore it. They are told apart by what they mean now, so the
        # name of the class changed with it.
        assert 'class="badge badge--name">pages-operator<' in markup, (
            "the role this account holds is not shown in the Roles column"
        )

    def test_the_edit_form_opens_with_the_held_roles_ticked(self, operator):
        """
        Otherwise the operator edits blind, and saving replaces the
        account's roles with whatever they happened to tick.
        """
        client, _, user_id = operator

        markup = page(client, f"/dashboard/users/{user_id}/edit")

        held = markup.split('value="pages-operator"')[1].split(">")[0]
        assert "checked" in held, "the role the account holds is not ticked"

    def test_the_role_of_anonymous_callers_is_not_offered(self, operator):
        """
        ``guest`` is what an unauthenticated request acts under. An account
        given it signs in to a dashboard it has no permission to read, and
        the form used to offer it as a choice.
        """
        client, _, user_id = operator

        markup = page(client, f"/dashboard/users/{user_id}/edit")

        assert 'value="guest"' not in markup


class TestTheUserListDoesNotStopAtTheFirstHundred:
    """
    The page rendered whatever ``list_users`` returned, which is its first
    hundred rows, and offered nothing to reach the rest: on a service with
    more accounts than that, the ones past the hundredth were reachable
    through the API and nowhere else.
    """

    def test_a_second_page_is_offered_when_there_is_one(self, app, operator):
        client, _, _ = operator
        register_enough_accounts(app, client)

        markup = page(client, "/dashboard/users?page=1")

        assert "page=2" in markup, "no way off the first page"

    def test_the_second_page_holds_different_accounts(self, app, operator):
        client, _, _ = operator
        register_enough_accounts(app, client)

        first = page(client, "/dashboard/users?page=1")
        second = page(client, "/dashboard/users?page=2")

        assert emails_on(first), "the first page is empty"
        assert emails_on(second), "the second page is empty"
        assert not (emails_on(first) & emails_on(second)), (
            "the two pages show the same accounts"
        )


class TestTheMenuOffersOnlyWhatTheCallerMayDo:

    def test_an_account_without_link_create_is_not_offered_it(self, reader):
        client, _, _ = reader

        markup = page(client, "/dashboard/")

        assert "Create Link" not in markup, (
            "offered a page whose endpoint answers 403 to this caller"
        )

    def test_an_account_with_stats_view_basic_can_reach_the_service_stats(
        self, reader
    ):
        """
        The permission was held and the link was drawn for two role names
        only, so this caller had the right and no way to use it.
        """
        client, _, _ = reader

        markup = page(client, "/dashboard/")

        assert "Service Stats" in markup

    def test_the_delete_button_follows_the_delete_permission(self, reader):
        """
        The column is drawn by the page script from this flag; a reader
        that may not delete used to be given the button anyway.
        """
        client, _, _ = reader

        markup = page(client, "/dashboard/links")

        assert 'data-can-delete="no"' in markup

    def test_an_account_that_may_delete_is_given_the_button(self, operator):
        client, _, _ = operator

        markup = page(client, "/dashboard/links")

        assert 'data-can-delete="yes"' in markup


class TestTheLandingPageOffersWhatItCanAnswer:

    def test_a_signed_out_visitor_is_not_offered_extended_info(self, client):
        """
        Extended figures go to the link's owner or a holder of
        ``stats:view_any``. A guest link belongs to nobody, so this button
        answered "Authentication required" every time it was pressed.
        """
        markup = page(client, "/")

        assert 'data-mode="extended"' not in markup

    def test_a_signed_out_visitor_is_still_offered_shortening(self, client):
        """The guest role carries ``link:create``; that is the whole point."""
        markup = page(client, "/")

        assert 'data-mode="single"' in markup

    def test_a_caller_without_link_create_is_offered_neither_form(self, reader):
        client, _, _ = reader

        markup = page(client, "/")

        assert 'data-mode="single"' not in markup
        assert 'data-mode="batch"' not in markup


class TestSystemRolesAreNotOfferedForEditing:

    def test_the_form_behind_the_hidden_link_refuses(self, operator):
        """
        The list hides Edit for a system role and the URL did not: the form
        rendered, and Save refused what it had just offered to do.

        Read off the code rather than off the wording. The page used to
        write its own sentence about system roles, and a test looking for
        "system role" in the markup passed on a page that had drifted from
        what the API says about the same rule -- which is exactly what had
        happened. The code is what says which refusal this is.
        """
        client, _, _ = operator

        response = client.get("/dashboard/roles/user/edit")

        assert response.status_code == 403
        assert "cannot be modified or deleted" in response.get_data(as_text=True)

    def test_the_page_and_the_api_say_the_same_thing(self, operator, app):
        """One rule, one sentence.

        The page used to word this refusal itself, and the two wordings had
        drifted: the API said "Cannot modify system roles" while the page
        said "The role X is a system role and cannot be modified". Both
        come from ``RoleIsSystemError`` now, so a change to the sentence
        moves both or neither.
        """
        client, token, _ = operator

        page = client.get("/dashboard/roles/user/edit")
        api = client.put(
            "/api/v1/admin/roles/user/permissions",
            json={"permissions": ["link:create"]},
            headers=csrf_headers(client, {"Authorization": f"Bearer {token}"}),
        )

        sentence = api.get_json()["message"]
        assert api.get_json()["error"] == "ROLE_IS_SYSTEM"
        assert sentence in page.get_data(as_text=True)


class TestOneLinksPageFetchesUnderTheReadersEntitlement:
    """The scope the charts on one link's page are fetched under.

    The tiles at the top of that page come from ``/links/<code>/extended``,
    which answers the link's owner, an administrator and a holder of
    ``stats:view_any``. The charts beneath them were fetched under
    ``scope=mine`` for all three, and the service applies the owner and the
    code as one condition -- so the third of those three was shown a link's
    five visits in the tiles and a chart saying it had none, with nothing on
    the screen to say which was the true one. Measured against the running
    stack before the fix: tiles ``clicks: 5``, charts ``total: 0``.
    """

    def test_a_holder_of_view_any_is_not_narrowed_to_their_own(
        self, any_links_analyst
    ):
        """Entitled to this link's traffic, and so asked for it."""
        client, _, _ = any_links_analyst

        markup = page(client, "/dashboard/links/lnkpg1/stats")

        assert 'data-visit-scope="service"' in markup
        assert 'data-visit-code="lnkpg1"' in markup

    def test_everybody_else_keeps_the_owner_condition(self, reader):
        """Not entitled to a stranger's traffic, so the second lock stays.

        The endpoint refuses a stranger's code on its own; this is what
        keeps that refusal from being the only thing between a guessable
        address and somebody else's figures.
        """
        client, _, _ = reader

        markup = page(client, "/dashboard/links/lnkpg2/stats")

        assert 'data-visit-scope="mine"' in markup
        assert 'data-visit-code="lnkpg2"' in markup
