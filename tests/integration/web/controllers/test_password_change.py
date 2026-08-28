"""The account holder changing their own password, over HTTP.

The unit tests beside this one hold the order of the two writes; these
hold what the order is *for*. A password change that leaves another
device signed in leaves whoever that device belongs to inside the
account, and the whole reason to change a password is usually that
somebody is.

Every account here gets its own client. A client that has signed in
carries the session cookies and stops being the caller a test meant --
which is how "the other device was signed out" comes out green against a
client that was never signed in as anybody else.

The addresses all carry a ``pw-`` prefix. The application under test is
built once for the whole session and its database outlives every test in
it, so an address is shared with whoever else spells it the same way --
and these tests change the password behind it. Written without the prefix,
this file took ``norefresh@example.com`` from
``tests/integration/web/middleware/test_authentication.py`` and left that
test unable to sign in, several files away and only when both ran.
"""

from tests.integration.conftest import auth_headers, confirm_email, csrf_headers


PASSWORD = "StrongPass1!"
"""The password every account in this file is registered with."""

NEW_PASSWORD = "EvenStronger2!"
"""What it is changed to."""


def an_account(app, email):
    """
    Register an account, confirm its address, and sign it in.

    Args:
        app: The application under test.
        email: Address to register.

    Returns:
        A tuple of the client that signed in and its access token.
    """
    client = app.test_client()
    client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    )
    confirm_email(app, email)
    signed_in = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    return client, signed_in.get_json()["access_token"]


def change(client, token, current=PASSWORD, new=NEW_PASSWORD):
    """
    Ask to change a password, as a signed-in caller.

    Args:
        client: The client making the request.
        token: Access token of the account making it.
        current: The password presented as the current one.
        new: The password asked for.

    Returns:
        The response.
    """
    return client.post(
        "/api/v1/auth/change-password",
        json={"current_password": current, "new_password": new},
        headers=csrf_headers(client, auth_headers(token)),
    )


class TestTheChangeTakes:
    """The password afterwards is the new one and not the old one."""

    def test_the_new_password_signs_in(self, app):
        client, token = an_account(app, "pw-changes@example.com")

        assert change(client, token).status_code == 200

        fresh = app.test_client()
        signed_in = fresh.post("/api/v1/auth/login", json={
            "email": "pw-changes@example.com", "password": NEW_PASSWORD
        })
        assert signed_in.status_code == 200

    def test_the_old_password_stops_signing_in(self, app):
        client, token = an_account(app, "pw-oldgone@example.com")

        change(client, token)

        fresh = app.test_client()
        refused = fresh.post("/api/v1/auth/login", json={
            "email": "pw-oldgone@example.com", "password": PASSWORD
        })
        assert refused.status_code == 401


class TestWhatIsRefused:
    """Four ways to be turned away, and none of them changes anything."""

    def test_an_anonymous_caller(self, app):
        anonymous = app.test_client()

        refused = anonymous.post("/api/v1/auth/change-password", json={
            "current_password": PASSWORD, "new_password": NEW_PASSWORD
        })

        assert refused.status_code == 401

    def test_a_wrong_current_password(self, app):
        client, token = an_account(app, "pw-wrongcurrent@example.com")

        refused = change(client, token, current="not-the-password")

        assert refused.status_code == 400
        # And the account still has the password it had: a refusal that
        # changed it anyway would answer 400 all the same.
        fresh = app.test_client()
        assert fresh.post("/api/v1/auth/login", json={
            "email": "pw-wrongcurrent@example.com", "password": PASSWORD
        }).status_code == 200

    def test_the_password_it_already_has(self, app):
        client, token = an_account(app, "pw-samepass@example.com")

        refused = change(client, token, new=PASSWORD)

        assert refused.status_code == 400

    def test_a_password_the_policy_refuses(self, app):
        client, token = an_account(app, "pw-weaknew@example.com")

        refused = change(client, token, new="123")

        assert refused.status_code == 400


class TestTheOtherDevices:
    """What the change does to sessions it was not made from."""

    def test_another_session_stops_authenticating(self, app):
        first, first_token = an_account(app, "pw-twodevices@example.com")
        # A second sign-in to the same account, from its own client --
        # this is the device the change is supposed to throw out.
        second = app.test_client()
        second_token = second.post("/api/v1/auth/login", json={
            "email": "pw-twodevices@example.com", "password": PASSWORD
        }).get_json()["access_token"]
        assert second.get(
            "/api/v1/links/mine", headers=auth_headers(second_token)
        ).status_code == 200

        change(first, first_token)

        # The access token is still a validly signed claim; what stopped
        # it is that the session it names has been revoked.
        assert second.get(
            "/api/v1/links/mine", headers=auth_headers(second_token)
        ).status_code == 401

    def test_another_session_cannot_refresh_its_way_back(self, app):
        first, first_token = an_account(app, "pw-norefresh@example.com")
        second = app.test_client()
        refresh_token = second.post("/api/v1/auth/login", json={
            "email": "pw-norefresh@example.com", "password": PASSWORD
        }).get_json()["refresh_token"]

        change(first, first_token)

        # The CSRF header goes with it: this client signed in, so it holds
        # the cookies, and without the header the answer is 403 from the
        # CSRF layer -- a refusal that says nothing about the session.
        refused = second.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
            headers=csrf_headers(second),
        )
        assert refused.status_code == 401


class TestTheDeviceThatMadeTheChange:
    """It is revoked with the rest and handed a new session in the answer."""

    def test_the_answer_carries_a_new_pair(self, app):
        client, token = an_account(app, "pw-newpair@example.com")

        answered = change(client, token)

        body = answered.get_json()
        assert body["access_token"] and body["refresh_token"]
        # Not the token it arrived with: that one names a session this
        # request revoked.
        assert body["access_token"] != token

    def test_the_new_pair_works(self, app):
        client, token = an_account(app, "pw-staysin@example.com")

        new_token = change(client, token).get_json()["access_token"]

        assert client.get(
            "/api/v1/links/mine", headers=auth_headers(new_token)
        ).status_code == 200

    def test_the_cookies_are_replaced_too(self, app):
        """The browser's half of it, which carries no header at all."""
        client, token = an_account(app, "pw-cookies@example.com")
        before = client.get_cookie("access_token").value

        change(client, token)

        after = client.get_cookie("access_token").value
        assert after != before
        # Read without a token: the page authenticates by cookie, and if
        # the answer had not replaced it the page would be signed out by
        # its own request.
        assert client.get("/api/v1/links/mine").status_code == 200


class TestAFieldThatWasNotSent:
    """Which field is missing is said, on every route that reads one.

    Five guards across three routes, and nothing reached any of them. A
    request missing a field is the ordinary shape of a broken client and
    of a form that lost a value, and what makes it fixable is being told
    which field -- so these hold the field name in ``details`` as well as
    the status. Answered by the global handler, which is what puts the
    name there.
    """

    def test_a_change_without_the_current_password(self, app):
        client, token = an_account(app, "pw-nocurrent@example.com")

        refused = client.post(
            "/api/v1/auth/change-password",
            json={"new_password": NEW_PASSWORD},
            headers=csrf_headers(client, auth_headers(token)),
        )

        assert refused.status_code == 400
        answer = refused.get_json()
        assert answer["error"] == "VALIDATION_ERROR"
        assert answer["details"][0]["field"] == "current_password"

    def test_a_change_without_the_new_password(self, app):
        client, token = an_account(app, "pw-nonew@example.com")

        refused = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": PASSWORD},
            headers=csrf_headers(client, auth_headers(token)),
        )

        assert refused.status_code == 400
        assert refused.get_json()["details"][0]["field"] == "new_password"

    def test_a_resend_without_an_address(self, app):
        refused = app.test_client().post(
            "/api/v1/auth/resend-verification", json={}
        )

        assert refused.status_code == 400
        assert refused.get_json()["details"][0]["field"] == "email"

    def test_a_reset_without_the_new_password(self, app):
        refused = app.test_client().post(
            "/api/v1/auth/reset-password", json={"token": "irrelevant"}
        )

        assert refused.status_code == 400
        assert refused.get_json()["details"][0]["field"] == "new_password"

    def test_a_reset_without_a_token(self, app):
        refused = app.test_client().post(
            "/api/v1/auth/reset-password", json={"new_password": NEW_PASSWORD}
        )

        assert refused.status_code == 400
        assert refused.get_json()["details"][0]["field"] == "token"
