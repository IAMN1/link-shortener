"""Integration tests for refresh token rotation and revocation."""

from datetime import datetime, timedelta, timezone

import jwt

from link_shortener.infrastructure.database.models.user_model import UserModel
from tests.integration.conftest import confirm_email
from tests.integration.conftest import (
    IntegrationTestConfig, arm_csrf, auth_headers, csrf_headers
)


def _login(client, email, password="StrongPass1!"):
    """
    Register and log in, leaving the session cookies in the client jar.

    Args:
        client: Flask test client.
        email: Email to register.
        password: Password to register with.

    Returns:
        The id of the logged-in user.
    """
    client.post("/api/v1/auth/register", json={
        "email": email, "password": password
    })
    confirm_email(client.application, email)
    r = client.post("/api/v1/auth/login", json={
        "email": email, "password": password
    })
    assert r.status_code == 200
    return r.get_json()["user"]["id"]


def _refresh(client):
    """
    Perform a refresh the way the browser does.

    Args:
        client: Flask test client holding the session cookies.

    Returns:
        The response object.
    """
    return client.post("/api/v1/auth/refresh", headers=csrf_headers(client))


class TestRotation:
    """Each refresh retires the token it was given."""

    def test_refresh_issues_a_new_refresh_token(self, app):
        client = app.test_client()
        _login(client, "rot-new@example.com")

        before = client.get_cookie("refresh_token").value
        assert _refresh(client).status_code == 200
        after = client.get_cookie("refresh_token").value

        assert after != before

    def test_rotation_can_repeat(self, app):
        client = app.test_client()
        _login(client, "rot-repeat@example.com")

        for _ in range(3):
            assert _refresh(client).status_code == 200

    def test_spent_token_is_refused(self, app):
        client = app.test_client()
        user_id = _login(client, "rot-spent@example.com")

        spent = client.get_cookie("refresh_token").value
        assert _refresh(client).status_code == 200

        thief = app.test_client()
        thief.set_cookie("refresh_token", spent, path="/")
        r = thief.post("/api/v1/auth/refresh", headers=arm_csrf(thief, user_id))
        assert r.status_code == 401


class TestReplayDetection:
    """A token coming back after it was spent is treated as stolen."""

    def test_replay_revokes_the_whole_chain(self, app):
        victim = app.test_client()
        user_id = _login(victim, "rot-replay@example.com")

        stolen = victim.get_cookie("refresh_token").value

        # The victim refreshes normally, which retires the stolen copy.
        assert _refresh(victim).status_code == 200

        # The thief tries the copy: it fails, and the alarm goes off.
        thief = app.test_client()
        thief.set_cookie("refresh_token", stolen, path="/")
        assert thief.post(
            "/api/v1/auth/refresh", headers=arm_csrf(thief, user_id)
        ).status_code == 401

        # The victim's current token is revoked too: at this point the copy
        # and the original cannot be told apart, so both must be retired.
        assert _refresh(victim).status_code == 401

    def test_replay_spares_the_users_other_devices(self, app):
        phone = app.test_client()
        user_id = _login(phone, "rot-blast@example.com")

        desktop = app.test_client()
        assert desktop.post("/api/v1/auth/login", json={
            "email": "rot-blast@example.com", "password": "StrongPass1!"
        }).status_code == 200

        stolen = phone.get_cookie("refresh_token").value
        assert _refresh(phone).status_code == 200

        thief = app.test_client()
        thief.set_cookie("refresh_token", stolen, path="/")
        assert thief.post(
            "/api/v1/auth/refresh", headers=arm_csrf(thief, user_id)
        ).status_code == 401

        # Only the compromised succession dies. Revoking everything would
        # turn one dead token -- out of a log or a backup -- into a way of
        # signing the user out everywhere, on demand.
        assert _refresh(phone).status_code == 401
        assert _refresh(desktop).status_code == 200

    def test_spent_token_cannot_sign_the_user_out_everywhere(self, app):
        victim = app.test_client()
        user_id = _login(victim, "rot-dos@example.com")

        second = app.test_client()
        assert second.post("/api/v1/auth/login", json={
            "email": "rot-dos@example.com", "password": "StrongPass1!"
        }).status_code == 200

        spent = victim.get_cookie("refresh_token").value
        assert _refresh(victim).status_code == 200

        # Someone who found a spent token replays it repeatedly.
        for _ in range(3):
            attacker = app.test_client()
            attacker.set_cookie("refresh_token", spent, path="/")
            assert attacker.post(
                "/api/v1/auth/refresh", headers=arm_csrf(attacker, user_id)
            ).status_code == 401

        assert _refresh(second).status_code == 200


class TestSessionOwnership:
    """A token may only spend the session that belongs to its subject."""

    def test_token_naming_someone_elses_session_is_refused(self, app):
        victim = app.test_client()
        _login(victim, "own-victim@example.com")
        victim_jti = jwt.decode(
            victim.get_cookie("refresh_token").value,
            IntegrationTestConfig.SECRET_KEY,
            algorithms=["HS256"],
        )["jti"]

        attacker = app.test_client()
        attacker_id = _login(attacker, "own-attacker@example.com")

        # Signed correctly, but points at the victim's session. Without the
        # ownership check this spent the victim's session and opened a new
        # one for the attacker.
        forged = jwt.encode(
            {
                "sub": attacker_id,
                "email": "own-attacker@example.com",
                "roles": ["user"],
                "exp": datetime.now(timezone.utc) + timedelta(days=1),
                "iat": datetime.now(timezone.utc),
                "type": "refresh",
                "jti": victim_jti,
            },
            IntegrationTestConfig.SECRET_KEY,
            algorithm="HS256",
        )

        client = app.test_client()
        client.set_cookie("refresh_token", forged, path="/")
        r = client.post(
            "/api/v1/auth/refresh", headers=arm_csrf(client, attacker_id)
        )
        assert r.status_code == 401

        # The victim's session is untouched.
        assert _refresh(victim).status_code == 200


class TestLogoutRevocation:
    """Logout ends the session on the server, not just in the browser."""

    def test_logout_kills_the_refresh_token(self, app):
        client = app.test_client()
        user_id = _login(client, "rot-logout@example.com")

        token = client.get_cookie("refresh_token").value
        assert client.post(
            "/api/v1/auth/logout", headers=csrf_headers(client)
        ).status_code == 200

        after = app.test_client()
        after.set_cookie("refresh_token", token, path="/")
        r = after.post("/api/v1/auth/refresh", headers=arm_csrf(after, user_id))
        assert r.status_code == 401

    def test_logout_leaves_other_devices_signed_in(self, app):
        phone = app.test_client()
        _login(phone, "rot-devices@example.com")

        desktop = app.test_client()
        r = desktop.post("/api/v1/auth/login", json={
            "email": "rot-devices@example.com", "password": "StrongPass1!"
        })
        assert r.status_code == 200

        assert phone.post(
            "/api/v1/auth/logout", headers=csrf_headers(phone)
        ).status_code == 200

        # Signing out on one device must not sign the user out everywhere.
        assert _refresh(desktop).status_code == 200


class TestAccessTokenRevocation:
    """Ending a session ends the access tokens it issued."""

    def test_access_token_stops_working_after_logout(self, app):
        client = app.test_client()
        _login(client, "revoke-access@example.com")
        access = client.get_cookie("access_token").value

        # A copy of the token, held somewhere the logout cannot reach.
        holder = app.test_client()
        assert holder.get(
            "/api/v1/links/mine", headers=auth_headers(access)
        ).status_code == 200

        assert client.post(
            "/api/v1/auth/logout", headers=csrf_headers(client)
        ).status_code == 200

        # Deleting the client's cookies would leave that copy usable for the
        # rest of the token's lifetime.
        assert holder.get(
            "/api/v1/links/mine", headers=auth_headers(access)
        ).status_code == 401

    def test_logout_leaves_other_devices_access_tokens_working(self, app):
        phone = app.test_client()
        _login(phone, "revoke-access-multi@example.com")

        desktop = app.test_client()
        r = desktop.post("/api/v1/auth/login", json={
            "email": "revoke-access-multi@example.com",
            "password": "StrongPass1!",
        })
        desktop_access = r.get_json()["access_token"]

        assert phone.post(
            "/api/v1/auth/logout", headers=csrf_headers(phone)
        ).status_code == 200

        assert desktop.get(
            "/api/v1/links/mine", headers=auth_headers(desktop_access)
        ).status_code == 200


class TestApiClientSession:
    """A client with no cookie jar must be able to run a whole session."""

    def _login_without_cookies(self, app, email):
        """
        Log in and drop the cookies, as a curl-style client would.

        Args:
            app: Flask application.
            email: Account to log in as.

        Returns:
            Tuple of (access_token, refresh_token).
        """
        client = app.test_client()
        client.post("/api/v1/auth/register", json={
            "email": email, "password": "StrongPass1!"
        })
        confirm_email(client.application, email)
        r = client.post("/api/v1/auth/login", json={
            "email": email, "password": "StrongPass1!"
        })
        assert r.status_code == 200
        body = r.get_json()
        return body["access_token"], body["refresh_token"]

    def test_login_hands_the_refresh_token_to_the_body(self, app):
        access, refresh = self._login_without_cookies(app, "api-body@example.com")
        assert access and refresh

    def test_refresh_works_from_the_body_without_cookies(self, app):
        _, refresh = self._login_without_cookies(app, "api-refresh@example.com")

        bare = app.test_client()
        r = bare.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
        assert r.status_code == 200

        body = r.get_json()
        assert body["access_token"]
        # Rotated, so the client has to keep the new one.
        assert body["refresh_token"] != refresh

        assert bare.get(
            "/api/v1/links/mine", headers=auth_headers(body["access_token"])
        ).status_code == 200

    def test_logout_works_with_only_a_bearer_token(self, app):
        access, _ = self._login_without_cookies(app, "api-logout@example.com")

        bare = app.test_client()
        assert bare.post(
            "/api/v1/auth/logout", headers=auth_headers(access)
        ).status_code == 200

        # Answering "Logged out" while revoking nothing would be a lie.
        assert bare.get(
            "/api/v1/links/mine", headers=auth_headers(access)
        ).status_code == 401

    def test_logout_from_the_body_revokes_the_session(self, app):
        access, refresh = self._login_without_cookies(app, "api-logout2@example.com")

        bare = app.test_client()
        assert bare.post(
            "/api/v1/auth/logout", json={"refresh_token": refresh}
        ).status_code == 200

        assert bare.post(
            "/api/v1/auth/refresh", json={"refresh_token": refresh}
        ).status_code == 401
        assert bare.get(
            "/api/v1/links/mine", headers=auth_headers(access)
        ).status_code == 401


class TestDeactivationRevocation:
    """A blocked account cannot refresh, whatever it still holds."""

    def test_deactivated_user_cannot_refresh(self, app, db):
        client = app.test_client()
        _login(client, "rot-blocked@example.com")

        with db.session() as session:
            model = session.query(UserModel).filter_by(
                email="rot-blocked@example.com"
            ).one()
            model.is_active = False

        assert _refresh(client).status_code == 401
