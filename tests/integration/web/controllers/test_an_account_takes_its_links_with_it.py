"""
Deleting an account, end to end -- the route with the most to destroy.

``DELETE /api/v1/admin/users/<id>`` was reached by nothing that let it
finish. The suite asks it for 403 and for 404 in five files; the one unit
test that gets a 200 out of it replaces the facade with a mock, so
everything below the controller -- the ownership sweep, the service, the
cache invalidation -- was answered by no test at all. The live run walks
it, and the live run is not in CI's default path.

What that leaves unheld is not the status code. The use case removes the
account's links inside the same transaction, on the reasoning written
above the line: either both go or neither does, because deleting the
account first would leave the links unowned and, if anything failed in
between, permanently so.

Which of these tests holds which mechanism was measured rather than
assumed, and the first two answers were wrong. Replacing
``uow.links.delete_by_owner(user_id)`` with ``[]`` leaves every assertion
below green: the links go anyway, because ``urls.owner_id`` carries
``ON DELETE CASCADE``. So the sweep is not what removes them -- it is
what produces the list the audit trail and the cache invalidation are
written from, and it is held here by asking for that trail.

The cascade is worth its own test for the same reason: it is the actual
guarantee, it lives in a migration, and a migration that dropped it would
leave rows behind pointing at an account that is gone.

Cache invalidation is *not* held here, and saying so is the point.
Deleting ``self._drop_cached(...)`` also leaves this file green, because
the testing profile answers every redirect from the database -- measured:
a link's row removed by ``DELETE`` alone stops redirecting at once. That
path needs a run with a live cache behind it, which is a different file
and a different fixture.

The account is deleted by an operator who is not the account, and who is
not the last administrator, so neither of the two refusals in front of
this path is what the test is measuring.
"""

from unittest.mock import patch

import pytest
from sqlalchemy import text

from tests.integration.conftest import (
    account_with_permissions, auth_headers, confirm_email,
)


PASSWORD = "Test1234!"
DESTINATION = "https://an-account-takes-its-links.example/one"
SECOND = "https://an-account-takes-its-links.example/two"


@pytest.fixture(scope="module")
def operator(app):
    """An account that may delete users, and read them back afterwards."""
    return account_with_permissions(
        app,
        "removes-accounts@example.test",
        PASSWORD,
        "removes-accounts",
        ["admin:manage_users", "admin:view_users"],
    )


def _row_count(app, sql, params):
    """One count out of the database under test."""
    with app.app_context():
        with app.container.get_db_manager().session() as session:
            return session.execute(text(sql), params).scalar_one()


@pytest.fixture()
def doomed(app):
    """A confirmed account holding two links of its own.

    Two rather than one: the sweep returns a list and the journal writes
    a record per link, and a loop that stops after the first is a shape a
    single link cannot tell apart from a correct one.
    """
    email = "doomed@example.test"
    client = app.test_client()
    client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    )
    confirm_email(app, email)
    token = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    ).get_json()["access_token"]

    codes = []
    for destination in (DESTINATION, SECOND):
        made = app.test_client().post(
            "/api/v1/shorten",
            json={"url": destination},
            headers=auth_headers(token),
        )
        assert made.status_code == 201, made.get_json()
        codes.append(made.get_json()["short_code"])

    user_id = _row_count(
        app, "SELECT id FROM users WHERE email = :e", {"e": email}
    )

    yield user_id, email, codes

    with app.app_context():
        with app.container.get_db_manager().session() as session:
            session.execute(
                text("DELETE FROM users WHERE email = :e"), {"e": email}
            )
            session.commit()


def _links_left(app, user_id):
    """How many links the database still says that account owns."""
    return _row_count(
        app,
        "SELECT count(*) FROM urls WHERE owner_id = :o",
        {"o": user_id},
    )


class TestTheAccountAndEverythingItOwned:

    def test_the_route_answers_that_it_deleted(self, app, operator, doomed):
        client, token, _ = operator
        user_id, _, _ = doomed

        answer = client.delete(
            f"/api/v1/admin/users/{user_id}", headers=auth_headers(token)
        )

        assert answer.status_code == 200, answer.get_json()
        assert answer.get_json()["message"] == "User deleted"

    def test_the_account_is_gone_from_the_database(self, app, operator, doomed):
        """Asked of the row, not of the answer.

        The controller turns a falsey return into a 404 and anything else
        into this message, so a service that reported success without
        writing would have produced the assertion above unchanged.
        """
        client, token, _ = operator
        user_id, email, _ = doomed

        client.delete(
            f"/api/v1/admin/users/{user_id}", headers=auth_headers(token)
        )

        assert _row_count(
            app, "SELECT count(*) FROM users WHERE email = :e", {"e": email}
        ) == 0

    def test_the_links_go_with_it(self, app, operator, doomed):
        """The end state, whatever brings it about.

        What brings it about is the cascade rather than the sweep -- see
        the test after this one, and the module docstring for how that
        was established.
        """
        client, token, _ = operator
        user_id, _, _ = doomed
        assert _links_left(app, user_id) == 2, "the fixture made no links"

        client.delete(
            f"/api/v1/admin/users/{user_id}", headers=auth_headers(token)
        )

        assert _links_left(app, user_id) == 0

    def test_the_cascade_is_what_takes_them(self, app, doomed):
        """The mechanism, asked of the database and not of the route.

        ``urls.owner_id`` is declared ``ON DELETE CASCADE``, and that is
        the guarantee the deletion actually rests on. It lives in a
        migration, which is the kind of place a constraint is quietly
        dropped: without it this route would leave rows pointing at an
        account that no longer exists, and the test above would still
        pass as long as the sweep ran.
        """
        user_id, email, _ = doomed
        assert _links_left(app, user_id) == 2, "the fixture made no links"

        with app.app_context():
            with app.container.get_db_manager().session() as session:
                session.execute(
                    text("DELETE FROM users WHERE email = :e"), {"e": email}
                )
                session.commit()

        assert _links_left(app, user_id) == 0

    def test_the_trail_names_every_link_that_was_destroyed(
        self, app, operator, doomed
    ):
        """What the sweep is really for.

        ``delete_by_owner`` hands back the links so that each one can be
        recorded: the deletion is not reversible, so the trail is the
        only remaining account of what was destroyed. Replacing it with
        an empty list leaves every other assertion in this file green,
        and reddens this one.

        Patched on the class of the object the use case will actually
        call, not on the instance the container hands out: every use case
        binds its request context first, and ``bind`` answers with a new
        logger. Patching the instance replaced a method nobody invokes --
        measured, the list came back empty. Wiring is captured when the
        container is built, so replacing a factory would do nothing
        either.
        """
        client, token, _ = operator
        user_id, _, codes = doomed
        use_case = app.container.get_delete_user_use_case()
        bound = use_case.audit_logger.bind()
        recorded = []

        with patch.object(
            type(bound),
            "log_url_deleted",
            autospec=True,
            side_effect=lambda self, **kw: recorded.append(kw["short_code"]),
        ):
            client.delete(
                f"/api/v1/admin/users/{user_id}", headers=auth_headers(token)
            )

        assert sorted(recorded) == sorted(codes), recorded

    def test_the_codes_stop_resolving(self, app, operator, doomed):
        """The end a visitor sees.

        Not a test of cache invalidation, though it looks like one: in
        this profile the redirect is answered from the database, so
        removing `_drop_cached` leaves this green. It is held here
        because a route may remove a row and leave the address resolving
        by some other path -- a second table, a fallback, a redirect
        rebuilt from the code.
        """
        client, token, _ = operator
        user_id, _, codes = doomed
        visitor = app.test_client()
        for code in codes:
            assert visitor.get(f"/{code}").status_code in (301, 302), (
                "the link did not redirect before the account was deleted"
            )

        client.delete(
            f"/api/v1/admin/users/{user_id}", headers=auth_headers(token)
        )

        for code in codes:
            assert visitor.get(f"/{code}").status_code == 404, code

    def test_the_account_cannot_sign_in_afterwards(self, app, operator, doomed):
        client, token, _ = operator
        user_id, email, _ = doomed

        client.delete(
            f"/api/v1/admin/users/{user_id}", headers=auth_headers(token)
        )

        refused = app.test_client().post(
            "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
        )
        assert refused.status_code == 401, refused.get_json()

    def test_the_journal_says_what_was_destroyed(
        self, app, operator, doomed, events
    ):
        """
        The count of links is part of the event and not a detail: the
        deletion is not reversible, so it is the only remaining measure
        of what went with the account.
        """
        client, token, _ = operator
        user_id, _, _ = doomed
        before = events("USER_DELETED")

        client.delete(
            f"/api/v1/admin/users/{user_id}", headers=auth_headers(token)
        )

        assert events("USER_DELETED") == before + 1
