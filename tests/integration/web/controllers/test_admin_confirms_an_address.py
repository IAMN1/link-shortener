"""
The two ways an operator deals with an address nobody confirmed.

Confirmation proves that whoever registered can read the mailbox. When the
message does not arrive -- no mail configured, a distribution list, a typo
in a domain that swallows it -- the account is stuck in a state that reads
as working: it is active, it is listed, and it cannot sign in. Before this
there was no way out of that state except an ``UPDATE`` against the
database.

So there are two: send the message again, and confirm on the operator's
word. The second bypasses the proof, which is why it is behind
``admin:manage_users``, says who did it in the log, and spends whatever
tokens were outstanding.
"""

import pytest
from sqlalchemy import text

from tests.integration.conftest import (
    account_with_permissions, auth_headers, register_and_login,
)


PASSWORD = "Test1234!"


@pytest.fixture(scope="module")
def operator(app):
    """An account that may manage users, and read them back."""
    return account_with_permissions(
        app,
        "confirms@example.test",
        PASSWORD,
        "confirms-addresses",
        ["admin:manage_users", "admin:view_users"],
    )


def unconfirmed_account(app, email):
    """
    Register an account and leave its address unconfirmed.

    That is what registration does on its own; the helper exists to say so
    at the call site, and to hand back the id the routes take.

    Args:
        app: The application under test.
        email: Address to register.

    Returns:
        The new account's id.
    """
    client = app.test_client()
    client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})

    with app.app_context():
        with app.container.get_db_manager().session() as session:
            row = session.execute(
                text("SELECT id, email_verified FROM users WHERE email = :e"),
                {"e": email},
            ).fetchone()

    assert row is not None, f"{email} was not registered"
    assert not row[1], "registration is supposed to leave the address unconfirmed"
    return row[0]


class TestConfirmingOnTheOperatorsWord:

    def test_it_confirms_and_says_so_in_the_answer(self, app, operator):
        client, token, _ = operator
        user_id = unconfirmed_account(app, "stuck@example.test")

        response = client.post(
            f"/api/v1/admin/users/{user_id}/verify-email",
            headers=auth_headers(token),
        )

        assert response.status_code == 200, response.get_json()
        assert response.get_json()["email_verified"] is True

    def test_the_account_can_then_sign_in(self, app, operator):
        """
        The point of the whole thing, and the only check that measures it.

        Asserting on the flag alone would pass on a change that sets the
        column and leaves login refusing for its own reasons.
        """
        client, token, _ = operator
        email = "can-sign-in@example.test"
        user_id = unconfirmed_account(app, email)

        refused = app.test_client().post(
            "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
        )
        # 401 and no more: an unconfirmed account is refused with the same
        # answer a wrong password gets, so the code no longer says which.
        # What is being measured here is that the refusal turns into a
        # sign-in once an operator confirms the address, and that does not
        # need the refusal to name itself.
        assert refused.status_code == 401

        client.post(
            f"/api/v1/admin/users/{user_id}/verify-email",
            headers=auth_headers(token),
        )

        allowed = app.test_client().post(
            "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
        )
        assert allowed.status_code == 200, allowed.get_json()

    def test_pressing_it_twice_is_not_an_error(self, app, operator):
        """
        Two operators, or one impatient one. Both want the same end state.
        """
        client, token, _ = operator
        user_id = unconfirmed_account(app, "twice@example.test")
        path = f"/api/v1/admin/users/{user_id}/verify-email"

        first = client.post(path, headers=auth_headers(token))
        second = client.post(path, headers=auth_headers(token))

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.get_json()["email_verified"] is True

    def test_an_outstanding_link_stops_working(self, app, operator):
        """
        A token that still works after the address is confirmed is a live
        credential sitting in a mailbox with nothing left to prove.
        """
        client, token, _ = operator
        email = "had-a-link@example.test"
        user_id = unconfirmed_account(app, email)

        client.post(
            f"/api/v1/admin/users/{user_id}/verify-email",
            headers=auth_headers(token),
        )

        with app.app_context():
            with app.container.get_db_manager().session() as session:
                outstanding = session.execute(
                    text(
                        "SELECT COUNT(*) FROM email_verifications "
                        "WHERE user_id = :u AND used_at IS NULL"
                    ),
                    {"u": user_id},
                ).fetchone()[0]

        assert outstanding == 0

    def test_an_account_that_is_not_there_is_a_404(self, operator):
        client, token, _ = operator

        response = client.post(
            "/api/v1/admin/users/00000000-0000-0000-0000-000000000000/verify-email",
            headers=auth_headers(token),
        )

        assert response.status_code == 404


class TestSendingTheMessageAgain:

    def test_it_is_addressed_by_id_and_answers_with_the_address(
        self, app, operator
    ):
        """
        By id, not by email: an operator acts on the account in front of
        them, and retyping an address is how mail goes to a typo.
        """
        client, token, _ = operator
        email = "wants-another@example.test"
        user_id = unconfirmed_account(app, email)

        response = client.post(
            f"/api/v1/admin/users/{user_id}/resend-verification",
            headers=auth_headers(token),
        )

        assert response.status_code == 202, response.get_json()
        assert email in response.get_json()["message"]

    def test_an_address_already_confirmed_is_not_reported_as_sent(
        self, app, operator
    ):
        """
        Nothing is sent for a confirmed account, and the answer used to
        claim otherwise.

        ``ResendVerificationUseCase`` writes no token and queues no message
        when the address is already confirmed -- it cannot, there is
        nothing left to confirm. The service returned the address anyway
        and the route dressed that as ``202 Confirmation message sent to
        ...``. Measured against a live mailbox: one message before the
        request, one after, and a 202 in between.

        200 rather than 202: nothing was accepted for delivery. The
        address still comes back, because the operator is looking at an
        account and the answer should name it.
        """
        client, token, _ = operator
        email = "already-confirmed@example.test"
        user_id = unconfirmed_account(app, email)
        client.post(
            f"/api/v1/admin/users/{user_id}/verify-email",
            headers=auth_headers(token),
        )

        response = client.post(
            f"/api/v1/admin/users/{user_id}/resend-verification",
            headers=auth_headers(token),
        )

        assert response.status_code == 200, response.get_json()
        message = response.get_json()["message"]
        assert email in message
        assert "sent" not in message.lower()

    def test_a_queue_that_refuses_the_message_is_not_reported_as_sent(
        self, app, operator, monkeypatch
    ):
        """
        The other way nothing goes out, and the one worth an alarm.

        ``enqueue_verification_email`` reports its failures -- its own port
        docstring says why: "the only way anyone finds out is if the
        service says so". Collapsed into one boolean with the case above,
        a broker that stopped accepting work would read as "that address
        is already confirmed", which is the same defect one level down.
        """
        client, token, _ = operator
        email = "queue-refuses@example.test"
        user_id = unconfirmed_account(app, email)

        with app.app_context():
            queue = app.container.get_task_queue()
            monkeypatch.setattr(
                queue, "enqueue_verification_email",
                lambda *args, **kwargs: False,
            )

            response = client.post(
                f"/api/v1/admin/users/{user_id}/resend-verification",
                headers=auth_headers(token),
            )

        assert response.status_code == 503, response.get_json()

    def test_the_refusal_says_what_did_not_happen_and_to_whom(
        self, app, operator, monkeypatch
    ):
        """
        The status alone was all this asked for, and the sentence behind
        it had gone missing: measured with the broker stopped, 503
        arrived as ``"message": "An internal error occurred"``.

        ``client_message`` blanks a 5xx sentence unless its code is
        listed, and the rule it applies is a proxy -- a 5xx usually
        describes the service's own state to somebody who is not the
        audience for it. Here the audience is an operator holding
        ``admin:manage_users``, the sentence was assembled for them with
        the address in it, and it is translated into both catalogues. So
        the one route that tells three answers apart told the operator
        exactly what every other failure tells them.
        """
        client, token, _ = operator
        email = "queue-refuses-out-loud@example.test"
        user_id = unconfirmed_account(app, email)

        with app.app_context():
            queue = app.container.get_task_queue()
            monkeypatch.setattr(
                queue, "enqueue_verification_email",
                lambda *args, **kwargs: False,
            )

            response = client.post(
                f"/api/v1/admin/users/{user_id}/resend-verification",
                headers=auth_headers(token),
            )

        body = response.get_json()
        assert body["error"] == "MAIL_NOT_HANDED_OFF"
        assert email in body["message"], body
        assert "internal error" not in body["message"].lower()

    def test_an_account_that_is_not_there_is_a_404(self, operator):
        """
        Unlike the public endpoint, which answers the same for every
        address on purpose. Here the caller already reads the account
        list, so there is nothing to hide and a wrong id is worth saying.
        """
        client, token, _ = operator

        response = client.post(
            "/api/v1/admin/users/00000000-0000-0000-0000-000000000000"
            "/resend-verification",
            headers=auth_headers(token),
        )

        assert response.status_code == 404


class TestTheListSaysWhichAccountsAreStuck:

    def test_the_flag_reaches_the_api(self, app, operator):
        """
        It did not: the DTO carried ``is_active`` and nothing about
        confirmation, so the admin list showed "Active" for an account
        that could not sign in.
        """
        client, token, _ = operator
        unconfirmed_account(app, "listed@example.test")

        listed = client.get("/api/v1/admin/users", headers=auth_headers(token))

        accounts = {u["email"]: u for u in listed.get_json()}
        assert "email_verified" in accounts["listed@example.test"]
        assert accounts["listed@example.test"]["email_verified"] is False

    def test_the_page_shows_both_states(self, app, operator):
        client, token, _ = operator
        register_and_login(app.test_client(), email="rendered@example.test")

        markup = client.get("/dashboard/users").get_data(as_text=True)

        assert "Not verified" in markup, (
            "the page shows no sign that an address is unconfirmed"
        )
        assert "js-confirm-email" in markup
        assert "js-resend-verification" in markup
