"""Recovering an account by mail, over HTTP.

Two routes and one rule between them: neither may say whether an address
is registered. The tests read that off the wire -- same status, same body
-- rather than off the code, because the code has four branches there and
the point is that the caller cannot see which one ran.

Tokens are issued here through the repository rather than read out of a
message: the suite's mailer sends nowhere, and only the digest is stored,
so there is no way to recover a mailed token afterwards. The whole chain
including the message is driven by ``tests/live/smoke_test.py``, which
raises a real SMTP receiver and takes the link out of what was delivered.

The addresses carry a ``pr-`` prefix for the reason the neighbouring file
gives: the application is built once for the session, its database
outlives every test, and these tests change the password behind an
address.
"""

from sqlalchemy import text

from tests.integration.conftest import auth_headers, confirm_email, csrf_headers

from link_shortener.domain.entities.password_reset import PasswordReset
from link_shortener.domain.value_objects.verification_token import (
    issue_token,
    token_digest,
)


PASSWORD = "StrongPass1!"
"""The password every account in this file is registered with."""

NEW_PASSWORD = "EvenStronger2!"
"""What it is reset to."""


def an_account(app, email, confirmed=True):
    """
    Register an account, optionally confirming its address.

    Args:
        app: The application under test.
        email: Address to register.
        confirmed: Whether to mark the address as proven.

    Returns:
        The client that registered it.
    """
    client = app.test_client()
    client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    )
    if confirmed:
        confirm_email(app, email)
    return client


def user_id_of(app, email):
    """
    The identifier of the account behind an address.

    Args:
        app: The application under test.
        email: Address to look up.

    Returns:
        The account id.
    """
    with app.app_context():
        with app.container.get_db_manager().session() as session:
            return session.execute(
                text("SELECT id FROM users WHERE email = :email"),
                {"email": email},
            ).scalar()


def issue_reset(app, email, ttl_minutes=60):
    """
    Put a reset token in the database and hand back the token itself.

    Written through the real repository, so the digest is computed the way
    the application computes it. The token is returned because this is the
    only moment it exists -- the row keeps a digest.

    Args:
        app: The application under test.
        email: Address of the account the token is for.
        ttl_minutes: How long it stays usable. A negative value issues one
            that is already expired.

    Returns:
        The token, as it would appear in the mailed link.
    """
    token = issue_token()
    with app.app_context():
        with app.container.get_uow_factory()() as uow:
            uow.password_resets.save(
                PasswordReset.issue(
                    user_id=user_id_of(app, email),
                    token_hash=token_digest(token),
                    ttl_minutes=ttl_minutes,
                )
            )
            uow.commit()
    return token


def reset_rows(app, email):
    """
    The reset tokens outstanding for an address.

    Args:
        app: The application under test.
        email: Address of the account.

    Returns:
        List of ``(id, used_at)`` pairs, spent ones included.
    """
    with app.app_context():
        with app.container.get_db_manager().session() as session:
            return session.execute(
                text(
                    "SELECT id, used_at FROM password_resets "
                    "WHERE user_id = :user_id"
                ),
                {"user_id": user_id_of(app, email)},
            ).all()


def ask_for_a_link(app, email):
    """
    Ask for a reset link, from a client that is nobody.

    Args:
        app: The application under test.
        email: Address to name in the request.

    Returns:
        The response.
    """
    return app.test_client().post(
        "/api/v1/auth/forgot-password", json={"email": email}
    )


def spend(app, token, new_password=NEW_PASSWORD):
    """
    Post a reset token and a new password.

    Args:
        app: The application under test.
        token: The token from the link.
        new_password: The password to set.

    Returns:
        The response.
    """
    return app.test_client().post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": new_password},
    )


def _without_timestamp(response) -> dict:
    """
    The body of an answer, minus the moment it was made.

    Args:
        response: The Flask test-client response to read.

    Returns:
        The JSON body without its ``timestamp`` field, so two answers can
        be compared for what they say rather than for when.
    """
    body = dict(response.get_json())
    body.pop("timestamp", None)
    return body


class TestAskingForALinkSaysNothing:
    """Four kinds of address, one answer."""

    def test_a_registered_and_an_unknown_address_answer_alike(self, app):
        an_account(app, "pr-known@example.com")

        known = ask_for_a_link(app, "pr-known@example.com")
        unknown = ask_for_a_link(app, "pr-nobody@example.com")

        assert known.status_code == unknown.status_code == 202
        assert _without_timestamp(known) == _without_timestamp(unknown)

    def test_a_link_is_issued_for_a_confirmed_account(self, app):
        an_account(app, "pr-issued@example.com")

        ask_for_a_link(app, "pr-issued@example.com")

        assert len(reset_rows(app, "pr-issued@example.com")) == 1

    def test_no_link_is_issued_for_an_unconfirmed_address(self, app):
        # The service has no evidence that this mailbox belongs to whoever
        # typed it into the registration form, and a reset link is a way
        # into the account.
        an_account(app, "pr-unconfirmed@example.com", confirmed=False)

        answered = ask_for_a_link(app, "pr-unconfirmed@example.com")

        assert answered.status_code == 202
        assert reset_rows(app, "pr-unconfirmed@example.com") == []

    def test_no_link_is_issued_for_a_deactivated_account(self, app, db):
        an_account(app, "pr-off@example.com")
        with app.app_context():
            with app.container.get_db_manager().session() as session:
                session.execute(
                    text(
                        "UPDATE users SET is_active = :off WHERE email = :email"
                    ),
                    {"email": "pr-off@example.com", "off": False},
                )
                session.commit()

        answered = ask_for_a_link(app, "pr-off@example.com")

        assert answered.status_code == 202
        assert reset_rows(app, "pr-off@example.com") == []

    def test_a_malformed_address_is_refused(self, app):
        refused = ask_for_a_link(app, "not-an-address")

        assert refused.status_code == 400

    def test_asking_twice_leaves_one_working_link(self, app):
        an_account(app, "pr-twice@example.com")
        first = issue_reset(app, "pr-twice@example.com")

        ask_for_a_link(app, "pr-twice@example.com")

        # The first link is retired rather than left beside the second:
        # otherwise the account is opened by whichever is used, including
        # one a stranger asked for an hour ago.
        assert spend(app, first).status_code == 400


class TestSpendingALink:
    """What the token buys, and what it stops buying afterwards."""

    def test_the_new_password_signs_in(self, app):
        an_account(app, "pr-works@example.com")
        token = issue_reset(app, "pr-works@example.com")

        assert spend(app, token).status_code == 200

        signed_in = app.test_client().post("/api/v1/auth/login", json={
            "email": "pr-works@example.com", "password": NEW_PASSWORD
        })
        assert signed_in.status_code == 200

    def test_the_old_password_stops_signing_in(self, app):
        an_account(app, "pr-oldgone@example.com")
        token = issue_reset(app, "pr-oldgone@example.com")

        spend(app, token)

        refused = app.test_client().post("/api/v1/auth/login", json={
            "email": "pr-oldgone@example.com", "password": PASSWORD
        })
        assert refused.status_code == 401

    def test_nobody_is_signed_in_by_it(self, app):
        an_account(app, "pr-nologin@example.com")
        token = issue_reset(app, "pr-nologin@example.com")

        client = app.test_client()
        answered = client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "new_password": NEW_PASSWORD},
        )

        assert answered.status_code == 200
        # No tokens in the body and no cookies in the jar: the account was
        # opened by a link out of a mailbox, and the first thing it should
        # ask for is the credential.
        assert "access_token" not in answered.get_json()
        assert client.get_cookie("access_token") is None

    def test_a_spent_link_cannot_be_spent_again(self, app):
        an_account(app, "pr-once@example.com")
        token = issue_reset(app, "pr-once@example.com")
        spend(app, token)

        again = spend(app, token, "ThirdPassword3!")
        unknown = spend(app, "no-such-token", "ThirdPassword3!")

        # Word for word what a token that never existed gets. "Already
        # used" would say an account exists and somebody reset it.
        assert again.status_code == unknown.status_code == 400
        assert _without_timestamp(again) == _without_timestamp(unknown)

    def test_an_expired_link_is_refused(self, app):
        an_account(app, "pr-expired@example.com")
        token = issue_reset(app, "pr-expired@example.com", ttl_minutes=-1)

        refused = spend(app, token)

        assert refused.status_code == 400
        # And the password is untouched.
        assert app.test_client().post("/api/v1/auth/login", json={
            "email": "pr-expired@example.com", "password": PASSWORD
        }).status_code == 200

    def test_a_password_the_policy_refuses_leaves_the_link_usable(self, app):
        an_account(app, "pr-weak@example.com")
        token = issue_reset(app, "pr-weak@example.com")

        refused = spend(app, token, "123")

        assert refused.status_code == 400
        # The claim rolled back with the refusal, so the person still has
        # a working link for their second attempt at a strong enough one.
        assert spend(app, token).status_code == 200


class TestTheSessionsGoWithIt:
    """A reset that leaves somebody signed in has changed nothing."""

    def test_every_session_stops_authenticating(self, app):
        an_account(app, "pr-sessions@example.com")
        first, second = app.test_client(), app.test_client()
        tokens = []
        for client in (first, second):
            answered = client.post("/api/v1/auth/login", json={
                "email": "pr-sessions@example.com", "password": PASSWORD
            })
            tokens.append(answered.get_json()["access_token"])
        for client, token in zip((first, second), tokens):
            assert client.get(
                "/api/v1/links/mine", headers=auth_headers(token)
            ).status_code == 200

        spend(app, issue_reset(app, "pr-sessions@example.com"))

        for client, token in zip((first, second), tokens):
            assert client.get(
                "/api/v1/links/mine", headers=auth_headers(token)
            ).status_code == 401


class TestChangingThePasswordRetiresTheLinks:
    """The other direction, and the reason it is not symmetry for its own sake."""

    def test_a_link_mailed_before_the_change_stops_working(self, app):
        client = an_account(app, "pr-raced@example.com")
        # A reset somebody else asked for, arriving in the owner's
        # mailbox. The owner notices and changes their password instead.
        stranger_link = issue_reset(app, "pr-raced@example.com")
        token = client.post("/api/v1/auth/login", json={
            "email": "pr-raced@example.com", "password": PASSWORD
        }).get_json()["access_token"]

        changed = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
            headers=csrf_headers(client, auth_headers(token)),
        )
        assert changed.status_code == 200

        # Without the retirement this answers 200 and the stranger is
        # inside the account the owner just secured.
        assert spend(app, stranger_link, "ThirdPassword3!").status_code == 400
