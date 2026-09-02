"""Integration tests for AuthenticationMiddleware with real DB."""

from link_shortener.infrastructure.database.unit_of_work import (
    SQLAlchemyUnitOfWork,
)
from link_shortener.infrastructure.database.models.user_model import UserModel
from tests.integration.conftest import confirm_email, auth_headers, csrf_headers


def _register_and_get_tokens(client, email, password="StrongPass1!"):
    """
    Register a user, log in, and return both tokens.

    Args:
        client: Flask test client.
        email: Email to register.
        password: Password to register with.

    Returns:
        Tuple of (access_token, refresh_token).
    """
    client.post("/api/v1/auth/register", json={
        "email": email, "password": password
    })
    confirm_email(client.application, email)
    r = client.post("/api/v1/auth/login", json={
        "email": email, "password": password
    })
    assert r.status_code == 200
    refresh_cookie = client.get_cookie("refresh_token")
    assert refresh_cookie is not None, "login must set the refresh_token cookie"
    return r.get_json()["access_token"], refresh_cookie.value


def _deactivate_user(db, email):
    """
    Flip ``is_active`` to False for the given user, as an admin block would.

    Args:
        db: Database manager.
        email: Email of the user to deactivate.
    """
    with db.session() as session:
        model = session.query(UserModel).filter_by(email=email).one()
        model.is_active = False



def _without_timestamp(response) -> dict:
    """
    The body of an error answer, minus the moment it was made.

    Args:
        response: The Flask test-client response to read.

    Returns:
        The JSON body without its ``timestamp`` field, so that two answers
        can be compared for what they say rather than for when.
    """
    body = dict(response.get_json())
    body.pop("timestamp", None)
    return body

class TestAuthenticationMiddleware:
    """Verify middleware loads user from JWT token correctly."""

    def test_valid_token_sets_current_user(self, client):
        client.post("/api/v1/auth/register", json={
            "email": "auth@example.com", "password": "StrongPass1!"
        })
        confirm_email(client.application, "auth@example.com")
        r = client.post("/api/v1/auth/login", json={
            "email": "auth@example.com", "password": "StrongPass1!"
        })
        token = r.get_json().get("access_token")

        # Access protected endpoint with valid token
        r = client.get("/api/v1/links/mine", headers=auth_headers(token))
        assert r.status_code == 200

    def test_invalid_token_rejected(self, client):
        r = client.get("/api/v1/links/mine", headers={
            "Authorization": "Bearer invalid.jwt.token"
        })
        assert r.status_code == 401

    def test_missing_token_allows_public_routes(self, client):
        # Public routes should work without token
        r = client.get("/health")
        assert r.status_code == 200

    def test_missing_token_blocks_protected_routes(self, client):
        r = client.get("/api/v1/admin/health")
        assert r.status_code == 401

    def test_expired_token_rejected(self, client):
        """
        A token whose ``exp`` has passed opens nothing.

        It used to register, sign in and assert that the **fresh** token
        answered 200 -- line for line the test above it, under a name
        promising the opposite. Nothing about expiry was exercised, so
        deleting the ``exp`` check from token validation left it green.
        The token is aged here the way
        ``test_a_presented_credential_is_not_ignored`` ages one: minted
        through the service with a negative lifetime, so it is this
        service's own signature over a moment that has gone.
        """
        import datetime

        from link_shortener.domain.value_objects.email import Email

        app = client.application
        client.post("/api/v1/auth/register", json={
            "email": "exp@example.com", "password": "StrongPass1!"
        })
        confirm_email(app, "exp@example.com")
        r = client.post("/api/v1/auth/login", json={
            "email": "exp@example.com", "password": "StrongPass1!"
        })
        fresh = r.get_json().get("access_token")
        assert fresh is not None

        with app.app_context():
            auth = app.container.get_authentication_service()
            claims = auth.validate_token(fresh, expected_type="access")
            with app.container.get_uow_factory()(read_only=True) as uow:
                user = uow.users.find_by_email(Email("exp@example.com"))
            expired = auth._create_token(
                user,
                datetime.timedelta(seconds=-30),
                "access",
                session_id=claims["sid"],
            )

        # The premise: the same account, the same session, the same
        # signature -- only the moment differs. Without this the assertion
        # below could be passing for any reason at all.
        r = client.get("/api/v1/links/mine", headers=auth_headers(fresh))
        assert r.status_code == 200

        r = client.get("/api/v1/links/mine", headers=auth_headers(expired))
        assert r.status_code == 401, r.get_data(as_text=True)[:200]


class TestTokenTypeEnforcement:
    """Only access tokens may authenticate a request."""

    def test_refresh_token_rejected_as_access_token(self, app):
        # A dedicated client keeps the login cookies out of the way, so the
        # request is authenticated by the Bearer header alone.
        login_client = app.test_client()
        _, refresh_token = _register_and_get_tokens(
            login_client, "reftype@example.com"
        )

        bare_client = app.test_client()
        r = bare_client.get(
            "/api/v1/links/mine", headers=auth_headers(refresh_token)
        )
        assert r.status_code == 401

    def test_access_token_still_accepted(self, app):
        login_client = app.test_client()
        access_token, _ = _register_and_get_tokens(
            login_client, "acctype@example.com"
        )

        bare_client = app.test_client()
        r = bare_client.get(
            "/api/v1/links/mine", headers=auth_headers(access_token)
        )
        assert r.status_code == 200


class TestDeactivatedUser:
    """Deactivating an account revokes access without waiting for expiry."""

    def test_deactivated_user_loses_api_access(self, app, db):
        login_client = app.test_client()
        access_token, _ = _register_and_get_tokens(
            login_client, "deactivated@example.com"
        )

        bare_client = app.test_client()
        r = bare_client.get(
            "/api/v1/links/mine", headers=auth_headers(access_token)
        )
        assert r.status_code == 200

        _deactivate_user(db, "deactivated@example.com")

        # The token is still cryptographically valid, but the account is not.
        r = bare_client.get(
            "/api/v1/links/mine", headers=auth_headers(access_token)
        )
        assert r.status_code == 401

    def test_deactivated_user_cannot_refresh(self, app, db):
        client = app.test_client()
        _register_and_get_tokens(client, "norefresh@example.com")

        _deactivate_user(db, "norefresh@example.com")

        r = client.post("/api/v1/auth/refresh", headers=csrf_headers(client))
        assert r.status_code == 401

    def test_deactivated_user_cannot_log_in(self, app, db):
        client = app.test_client()
        _register_and_get_tokens(client, "nologin@example.com")

        _deactivate_user(db, "nologin@example.com")

        # A fresh client, for the reason the next test spells out: the
        # logged-in one carries session cookies, so the CSRF layer turns its
        # login away before the credential check runs. That answer is 403,
        # and pinning it would pin the CSRF middleware instead of the
        # deactivation -- measured, with `if not user.is_active` deleted the
        # test stayed green.
        prober = app.test_client()

        r = prober.post("/api/v1/auth/login", json={
            "email": "nologin@example.com", "password": "StrongPass1!"
        })
        assert r.status_code == 401

    def test_deactivated_account_does_not_confirm_a_correct_password(self, app, db):
        client = app.test_client()
        _register_and_get_tokens(client, "blockedsame@example.com")

        _deactivate_user(db, "blockedsame@example.com")

        # A fresh client: the logged-in one still carries session cookies,
        # so its login attempts would be turned away by the CSRF layer before
        # reaching the credential check, and both answers would match for the
        # wrong reason.
        prober = app.test_client()
        right = prober.post("/api/v1/auth/login", json={
            "email": "blockedsame@example.com", "password": "StrongPass1!"
        })
        wrong = prober.post("/api/v1/auth/login", json={
            "email": "blockedsame@example.com", "password": "WrongPass1!"
        })

        # Answering differently would tell an attacker that the guessed
        # password is the right one, blocked account or not. The envelope's
        # timestamp is stamped per answer and left out of the comparison.
        assert right.status_code == 401
        assert right.status_code == wrong.status_code
        assert _without_timestamp(right) == _without_timestamp(wrong)


class TestADatabaseThatStoppedAnswering:
    """The hook runs before every view, so its failure is every route's.

    ``load_current_user`` opens a unit of work on every request that
    carries a token. An outage there used to be a 500 on routes that need
    no database at all -- ``/health`` among them, whose whole purpose is
    to report that outage, and which then reported nothing but a crash.
    The request continues as anonymous instead, and the failure goes to
    the log.

    The claim was written down in the middleware and measured by nothing.

    The outage is made by breaking ``SQLAlchemyUnitOfWork.__enter__``,
    not by replacing anything on the container. Everything was wired at
    application start and holds the factory itself, so a container whose
    accessor is swapped afterwards hands the new one to nobody -- written
    that way first, this checked a working database and passed.
    """

    @staticmethod
    def _break_it(monkeypatch):
        """Every unit of work opened from now on fails to open."""
        def refuses(self):
            raise RuntimeError("connection to the database was refused")

        monkeypatch.setattr(SQLAlchemyUnitOfWork, "__enter__", refuses)

    def test_the_health_probe_is_not_a_crash(self, app, monkeypatch):
        """It exists to report an outage, so it must survive one.

        With a token, deliberately: without one the hook returns before
        it opens anything, so the outage never reaches the branch this
        is about and the check passes without measuring it -- which is
        how it was written first.
        """
        client = app.test_client()
        token, _ = _register_and_get_tokens(client, "outage-health@example.com")
        self._break_it(monkeypatch)

        response = app.test_client().get("/health", headers=auth_headers(token))

        assert response.status_code != 500, response.get_data(as_text=True)

    def test_a_live_token_goes_on_as_anonymous(self, app, monkeypatch):
        """The account cannot be read, so the caller is nobody.

        Not "let through on the token's word": the token is a signed
        claim, and what the database was being asked is whether the
        session behind it still lives and whether the account is still
        active. With no answer to either, the safe reading is anonymous.
        """
        client = app.test_client()
        token, _ = _register_and_get_tokens(client, "outage-anon@example.com")

        self._break_it(monkeypatch)

        response = app.test_client().get(
            "/api/v1/links/mine", headers=auth_headers(token)
        )

        assert response.status_code == 401, response.get_data(as_text=True)
        assert response.get_json()["error"] == "UNAUTHENTICATED"
