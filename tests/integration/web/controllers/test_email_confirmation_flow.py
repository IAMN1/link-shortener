"""The confirmation path as a caller sees it, over HTTP.

Registration, the refusal to sign in, the link, and signing in afterwards.
The token is read out of the database rather than out of a mailbox --
nothing is mailed in the suite, and only the digest is stored -- so the
test issues its own and stores the digest, which is what registration
would have left behind.
"""

import pytest
from sqlalchemy import text

from link_shortener.domain.value_objects.verification_token import (
    issue_token,
    token_digest,
)
from tests.integration.conftest import auth_headers, confirm_email


PASSWORD = "StrongPass1!"


@pytest.fixture
def email(request):
    """A fresh address for each test.

    The application fixture is session-scoped, so one database is shared
    by the whole suite and an address registered in one test is still
    registered in the next. Reusing a constant here made a test pass or
    fail depending on what ran before it.
    """
    return f"confirm-{request.node.name}@example.test".replace("[", "-").replace(
        "]", ""
    ).replace(" ", "")


def _register(client, email, password=PASSWORD):
    """Register an account and return the response."""
    return client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )


def _sign_in(client, email, password=PASSWORD):
    """Attempt to sign in and return the response."""
    return client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )


def _issue_link_token(app, email, ttl_hours=24, used=False):
    """Store a confirmation for an account and hand back its raw token.

    Args:
        app: The application under test.
        email: Address of the account.
        ttl_hours: Lifetime of the confirmation.
        used: Whether to store it already spent.

    Returns:
        The token that opens it.
    """
    from datetime import datetime, timedelta, timezone
    import uuid

    token = issue_token()
    now = datetime.now(timezone.utc)
    with app.app_context():
        with app.container.get_db_manager().session() as session:
            user_id = session.execute(
                text("SELECT id FROM users WHERE email = :email"), {"email": email}
            ).scalar()
            assert user_id, f"{email} was never registered"
            session.execute(
                text(
                    "INSERT INTO email_verifications "
                    "(id, user_id, token_hash, expires_at, created_at, used_at) "
                    "VALUES (:id, :user_id, :hash, :expires, :created, :used)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "user_id": user_id,
                    "hash": token_digest(token),
                    "expires": now + timedelta(hours=ttl_hours),
                    "created": now,
                    "used": now if used else None,
                },
            )
            session.commit()
    return token


def _is_verified(app, email):
    """Read the confirmation flag straight out of the table."""
    with app.app_context():
        with app.container.get_db_manager().session() as session:
            return session.execute(
                text("SELECT email_verified FROM users WHERE email = :email"),
                {"email": email},
            ).scalar()


class TestRegistrationLeavesAnAccountWaiting:
    """What a fresh registration can and cannot do."""

    def test_registration_still_succeeds(self, client, email):
        assert _register(client, email).status_code == 202

    def test_the_account_is_not_confirmed(self, client, app, email):
        _register(client, email)

        assert _is_verified(app, email) == 0

    def test_a_confirmation_row_was_written(self, client, app, email):
        """Counted for this account only: the database is shared by the
        whole session, so a total would be counting everyone."""
        _register(client, email)

        with app.app_context():
            with app.container.get_db_manager().session() as session:
                rows = session.execute(
                    text(
                        "SELECT COUNT(*) FROM email_verifications v "
                        "JOIN users u ON u.id = v.user_id WHERE u.email = :email"
                    ),
                    {"email": email},
                ).scalar()

        assert rows == 1

    def test_signing_in_is_refused_until_the_address_is_confirmed(self, client, email):
        _register(client, email)

        response = _sign_in(client, email)

        assert response.status_code == 401

    def test_the_refusal_is_the_one_a_wrong_password_gets(self, client, email):
        """
        Named until it was measured as an oracle.

        The refusal used to be ``EMAIL_NOT_VERIFIED``, on the argument that
        only a caller who already knows the password ever sees it, so it
        reveals no account they had not found. True, and beside the point:
        what it reveals is that the guess *landed*, and a password is worth
        having away from this service because people reuse them. Measured
        on a live stack, the pair ``EMAIL_NOT_VERIFIED`` for the right
        password and ``INVALID_CREDENTIALS`` for a wrong one answers "is
        this the password" to anybody who asks.

        The holder is not stranded: the sign-in page carries "Didn't get
        the confirmation email?" at all times, and that route answers 202
        for any address.
        """
        _register(client, email)

        unconfirmed = _sign_in(client, email)
        wrong_password = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "NotThePassword9!"},
        )

        assert unconfirmed.status_code == wrong_password.status_code
        assert (
            unconfirmed.get_json()["error"]
            == wrong_password.get_json()["error"]
            == "INVALID_CREDENTIALS"
        )
        assert (
            unconfirmed.get_json()["message"]
            == wrong_password.get_json()["message"]
        )

    def test_the_journal_still_knows_which_it_was(self, client, app, email):
        """
        The wire drops the distinction; the journal keeps it.

        That is what ``log_login_failed`` takes a reason for, and it is
        the arrangement the deactivated-account branch beside it already
        used: an operator has to tell "somebody is guessing" from "a real
        user never confirmed", and ``audit:view`` separates that reader
        from the caller.
        """
        from sqlalchemy import text

        _register(client, email)
        _sign_in(client, email)

        with app.app_context():
            with app.container.get_db_manager().session() as session:
                reasons = session.execute(
                    text(
                        "SELECT count(*) FROM security_events "
                        "WHERE event_type = 'LOGIN_FAILED'"
                    )
                ).scalar_one()

        assert reasons >= 1


class TestFollowingTheLink:
    """The route the confirmation message points at."""

    def test_a_live_token_confirms_the_address(self, client, app, email):
        _register(client, email)
        token = _issue_link_token(app, email)

        response = client.get(f"/api/v1/auth/verify?token={token}")

        assert response.status_code == 200
        assert _is_verified(app, email) == 1

    def test_signing_in_works_afterwards(self, client, app, email):
        _register(client, email)
        token = _issue_link_token(app, email)
        client.get(f"/api/v1/auth/verify?token={token}")

        response = _sign_in(client, email)

        assert response.status_code == 200
        assert "access_token" in response.get_json()

    def test_the_link_works_once(self, client, app, email):
        _register(client, email)
        token = _issue_link_token(app, email)
        client.get(f"/api/v1/auth/verify?token={token}")

        response = client.get(f"/api/v1/auth/verify?token={token}")

        assert response.status_code == 400

    @pytest.mark.parametrize(
        "query", ["token=never-issued", "token=", ""]
    )
    def test_a_token_that_is_not_one_is_refused(self, client, app, query, email):
        _register(client, email)

        response = client.get(f"/api/v1/auth/verify?{query}")

        assert response.status_code == 400
        assert _is_verified(app, email) == 0

    def test_an_expired_token_is_refused(self, client, app, email):
        _register(client, email)
        token = _issue_link_token(app, email, ttl_hours=-1)

        response = client.get(f"/api/v1/auth/verify?token={token}")

        assert response.status_code == 400
        assert _is_verified(app, email) == 0

    def test_every_refusal_reads_the_same(self, client, app, email):
        """Told apart, this route reports whether an address is registered
        and whether it was confirmed.

        Five ways in, counting a blank token and a missing one -- the
        fourth kind, a token naming a deleted account, cannot be produced
        over HTTP: the foreign key refuses a confirmation for an account
        that does not exist, and the cascade removes them with it. That
        one is covered in the unit tests.

        Statuses are compared as well as bodies: an answer that says the
        same thing under a different status has still said which case it
        was.
        """
        _register(client, email)
        spent = _issue_link_token(app, email, used=True)
        expired = _issue_link_token(app, email, ttl_hours=-1)

        answers = set()
        for query in [
            f"token={spent}",
            f"token={expired}",
            "token=never-issued",
            "token=",
            "",
        ]:
            response = client.get(f"/api/v1/auth/verify?{query}")
            body = dict(response.get_json())
            body.pop("timestamp", None)
            answers.add((response.status_code, repr(sorted(body.items()))))

        assert len(answers) == 1, answers


class TestAskingForAnotherMessage:
    """The resend route, which must answer the same for everyone."""

    def test_an_unconfirmed_account_is_accepted(self, client, email):
        _register(client, email)

        response = client.post(
            "/api/v1/auth/resend-verification", json={"email": email}
        )

        assert response.status_code == 202

    def test_an_unknown_address_answers_identically(self, client, email):
        """The whole point: a route that mails on request and answers
        honestly tells anyone who asks who is registered."""
        _register(client, email)
        registered = client.post(
            "/api/v1/auth/resend-verification", json={"email": email}
        )
        unknown = client.post(
            "/api/v1/auth/resend-verification",
            json={"email": "nobody-at-all@example.com"},
        )

        assert unknown.status_code == registered.status_code
        assert unknown.get_json()["message"] == registered.get_json()["message"]

    def test_a_confirmed_address_answers_identically_too(self, client, app, email):
        _register(client, email)
        confirm_email(app, email)

        response = client.post(
            "/api/v1/auth/resend-verification", json={"email": email}
        )
        unknown = client.post(
            "/api/v1/auth/resend-verification",
            json={"email": "nobody-at-all@example.com"},
        )

        assert response.status_code == unknown.status_code
        assert response.get_json()["message"] == unknown.get_json()["message"]

    def test_a_new_request_retires_the_previous_link(self, client, app, email):
        """Otherwise every request leaves another working link behind."""
        _register(client, email)
        old = _issue_link_token(app, email)

        client.post("/api/v1/auth/resend-verification", json={"email": email})

        assert client.get(f"/api/v1/auth/verify?token={old}").status_code == 400

    @pytest.mark.parametrize("body", [{}, {"email": ""}, {"email": 5}])
    def test_a_request_with_no_address_is_a_bad_request(self, client, body):
        response = client.post("/api/v1/auth/resend-verification", json=body)

        assert response.status_code == 400


class TestAdministratorsAreNotHeldUp:
    """An account an administrator created has nobody to mail."""

    def test_an_admin_created_account_can_sign_in(self, app, client, email):
        from link_shortener.infrastructure.database.seed import seed_base_roles

        with app.app_context():
            with app.container.get_db_manager().session() as session:
                seed_base_roles(session)

        admin_client = app.test_client()
        admin_client.post(
            "/api/v1/auth/register",
            json={"email": "the-admin@example.com", "password": PASSWORD},
        )
        confirm_email(app, "the-admin@example.com")
        with app.app_context():
            with app.container.get_db_manager().session() as session:
                session.execute(
                    text(
                        "INSERT INTO user_roles (user_id, role_id) SELECT u.id, "
                        "r.id FROM users u, roles r WHERE u.email = "
                        "'the-admin@example.com' AND r.name = 'admin'"
                    )
                )
                session.commit()
        token = admin_client.post(
            "/api/v1/auth/login",
            json={"email": "the-admin@example.com", "password": PASSWORD},
        ).get_json()["access_token"]

        made = admin_client.post(
            "/api/v1/admin/users",
            headers=auth_headers(token),
            json={
                "email": "made-by-admin@example.com",
                "password": PASSWORD,
                "roles": ["user"],
                "is_active": True,
            },
        )
        assert made.status_code in (200, 201), made.get_json()

        signed_in = app.test_client().post(
            "/api/v1/auth/login",
            json={"email": "made-by-admin@example.com", "password": PASSWORD},
        )

        assert signed_in.status_code == 200, signed_in.get_json()


class TestADeploymentThatCannotRegisterAnybody:
    """The default role is missing, and the person is told so in their language.

    A code of its own -- ``REGISTRATION_UNAVAILABLE`` -- because it used to
    share ``CONFIGURATION_ERROR`` with ``UserManagementService``, whose
    sentence names a role from the configuration and belongs in a log. One
    code cannot have two audiences: whatever rule decides whether a
    sentence may be shown has to be right about both at once, and the rule
    (a 5xx code says nothing to the client) was right about one.

    So this one is listed in ``CODES_WORDED_FOR_THE_CLIENT``, and what
    these hold is the two halves of that: the sentence a person sees, and
    the sentence they do not.
    """

    @pytest.fixture
    def application(self):
        """An application whose default role is not in the database."""
        from link_shortener.web.app_factory import create_app
        from tests.integration.conftest import IntegrationTestConfig

        class NoDefaultRoleConfig(IntegrationTestConfig):
            DEFAULT_ROLE_NAME = "a-role-nobody-seeded"

        from link_shortener.infrastructure.database.seed import seed_base_roles

        application = create_app(config=NoDefaultRoleConfig())
        application.config["TESTING"] = True
        with application.app_context():
            db = application.container.get_db_manager()
            db.create_tables()
            # Seeded, and the configured name is still not among them:
            # what is missing is the role this deployment was told to
            # give new accounts, not the whole table.
            with db.session() as session:
                seed_base_roles(session)
        return application

    def test_the_registration_is_refused_by_its_own_code(self, application):
        response = application.test_client().post(
            "/api/v1/auth/register",
            json={
                "email": "nobody-can-register@example.test",
                "password": "Str0ng!Passw0rd",
            },
        )

        assert response.status_code == 400, response.get_json()
        assert response.get_json()["error"] == "REGISTRATION_UNAVAILABLE"

    def test_the_sentence_is_shown_and_says_nothing_about_the_deployment(
        self, application
    ):
        response = application.test_client().post(
            "/api/v1/auth/register",
            json={
                "email": "nobody-can-register-2@example.test",
                "password": "Str0ng!Passw0rd",
            },
        )

        message = response.get_json()["message"]
        assert message == "Registration is unavailable"
        # The name of the role is the part an anonymous caller must not be
        # handed: it says which part of the deployment is misconfigured.
        assert "a-role-nobody-seeded" not in response.get_data(as_text=True)

    def test_it_is_shown_in_the_language_of_the_request(self, application):
        """The reason the sentence is marked at all.

        Every other 5xx-coded sentence is replaced by a generic one before
        it reaches anybody, so marking it would put the service's
        internals in front of a translator. This one is read by whoever
        pressed Register, which is what the exception list records.
        """
        client = application.test_client()
        client.set_cookie("lang", "ru", domain="localhost")

        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "nobody-can-register-3@example.test",
                "password": "Str0ng!Passw0rd",
            },
        )

        assert response.get_json()["message"] == "Регистрация сейчас недоступна"
