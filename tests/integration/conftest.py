"""
Shared fixtures for integration tests.

All integration tests use a real in-memory SQLite database.
Fixtures provide app, client, db_manager, and authenticated helpers.
"""

import pytest
from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.web.app_factory import create_app
from link_shortener.web.middleware.csrf import (
    CSRF_COOKIE_NAME, CSRF_HEADER_NAME, build_csrf_token
)


class IntegrationTestConfig(TestingConfig):
    """Config for integration tests: real DB, no external services."""
    TESTING = True
    DEBUG = False
    SECRET_KEY = "integration-test-secret"
    SHORT_CODE_SECRET_PEPPER = "integration-test-pepper"
    DATABASE_URL = "sqlite:///:memory:"
    REDIS_ENABLED = False
    CACHE_ENABLED = False
    LOGGING_ENABLED = False
    AUDIT_ENABLED = False
    AUTO_SEED_ROLES = False
    BASE_URL = "http://testserver/"
    HOST = "testserver"
    PORT = 80
    COOKIE_SECURE = False
    RATE_LIMIT_AUTH_DISABLED = True

    GUEST_LINK_LIMIT = 20
    """Raised from the default ten, because the suite shares one allowance.

    The ``app`` fixture is session-scoped, a guest's allowance is counted
    per address, and every test that shortens without naming an address
    spends from the same pool. At the default the pool for ``127.0.0.1`` is
    spent to its last unit, so one further guest creation anywhere in
    ``tests/integration`` reddens an unrelated CSRF test with
    429 -- a failure that names neither the quota nor the test that took
    the last one.

    Twenty rather than something larger: the throttle on
    ``api.create_short_link`` is 30 requests a minute, and a quota at or
    above it is reached second, so a test that spends its allowance to ask
    what a refusal says measures the throttle instead -- ``Retry-After:
    60`` where the quota says 86400, with the throttle's counters attached.
    At 30 three tests fail that way, at 29 none do. They are the tests that
    name their own address, which keeps them clear of this
    pool but not of this number: they spend ``limit + 1`` requests to reach
    a refusal, so raising the quota raises what they send.

    This is a wider allowance, not an isolated one, and the room it buys is
    finite: measured, the suite spends 10 of the 20, so ten further guest
    creations on the shared address pass and the eleventh reddens that same
    CSRF test again. A test that cares about the quota -- or that creates
    guest links in any number -- should name its own address, as the ones
    in ``test_link_creation_limits.py`` do.
    """


@pytest.fixture(scope="session")
def app():
    """Create Flask app once per test session with real in-memory DB."""
    application = create_app(config=IntegrationTestConfig())
    application.config["TESTING"] = True

    with application.app_context():
        db_manager = application.container.get_db_manager()
        db_manager.create_tables()
        from link_shortener.infrastructure.database.seed import seed_base_roles
        with db_manager.session() as session:
            seed_base_roles(session)

    yield application

    with application.app_context():
        application.container.close()


@pytest.fixture()
def client(app):
    """Fresh test client per test."""
    return app.test_client()


@pytest.fixture()
def db(app):
    """Database manager for direct DB operations."""
    with app.app_context():
        yield app.container.get_db_manager()


def confirm_email(app, email):
    """
    Mark a registered address as confirmed, as following the link would.

    Registration leaves the account unconfirmed and login refuses it until
    the address is proven, so a test that wants a working account has to
    do here what a person does by opening their mail. It cannot be done
    through the real route: only the digest of the token is stored, and
    the token itself exists for the length of one call to the mailer,
    which is a ``NullMailer`` in the suite.

    Args:
        app: The application under test.
        email: Address of the account to confirm.
    """
    from sqlalchemy import text

    with app.app_context():
        with app.container.get_db_manager().session() as session:
            # ``True``, not ``1``: SQLite takes either, PostgreSQL refuses
            # the integer for a boolean column, so the literal form worked
            # for as long as no test ran against a real database.
            session.execute(
                text(
                    "UPDATE users SET email_verified = :verified "
                    "WHERE email = :email"
                ),
                {"email": email, "verified": True},
            )
            session.commit()


def register_and_login(client, email="test@example.com", password="Test1234!"):
    """Helper: register a user, confirm the address, return access token."""
    client.post("/api/v1/auth/register", json={
        "email": email, "password": password
    })
    confirm_email(client.application, email)
    r = client.post("/api/v1/auth/login", json={
        "email": email, "password": password
    })
    data = r.get_json()
    return data.get("access_token")


def auth_headers(token):
    """Helper: build Authorization headers from token."""
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def only_this_role(app, user_id, role_name):
    """
    Leave the account holding one role.

    ``account_with_permissions`` adds a role to the default ``user`` one
    rather than replacing it, so an account built to lack a permission
    holds it anyway -- and a check that something is refused would pass or
    fail for the wrong reason.

    Here rather than in one test file because two of them need it: what
    one permission opens is a question about the account holding exactly
    it, and the default role carries four permissions of its own.

    Args:
        app: The application under test.
        user_id: Account to strip.
        role_name: The single role it is to keep.
    """
    from sqlalchemy import text

    with app.app_context():
        with app.container.get_db_manager().session() as session:
            session.execute(
                text(
                    "DELETE FROM user_roles WHERE user_id = :uid AND role_id IN "
                    "(SELECT id FROM roles WHERE name != :keep)"
                ),
                {"uid": user_id, "keep": role_name},
            )
            session.commit()


def account_with_permissions(app, email, password, role_name, permissions):
    """
    Register an account and add a role holding these permissions.

    Written for the tests that ask what one permission opens and what it
    does not. The account is given its own client, because a client that
    has logged in carries a session cookie and stops being the caller the
    test meant.

    *Added*, not "given only": registration grants the default role as
    well, so the account ends up with two roles. An account built with
    ``["admin:view_system_health"]`` alone carries roles ``only-probe`` and
    ``user``, permissions ``admin:view_system_health``,
    ``link:create``, ``link:delete_own``, ``link:view_own`` and
    ``stats:view_basic``. None of the default four is administrative --
    ``test_every_admin_route_is_guarded`` is what holds that -- so a
    refusal here is still about the permission under test, but a caller
    reading "exactly these" would have been misled.

    Args:
        app: The application under test.
        email: Address to register.
        password: Password to register and log in with.
        role_name: Name for the role created for this account.
        permissions: Permission names the new role is to hold.

    Returns:
        Tuple of (fresh client, access token, the account's own user id).
        The id is handed back because a route that takes one has to be
        asked about something that exists: a 404 from a made-up id reads
        like a refusal and would let a positive check pass on it.
    """
    import uuid

    from sqlalchemy import text

    from link_shortener.infrastructure.database.seed import seed_base_roles

    with app.app_context():
        with app.container.get_db_manager().session() as session:
            seed_base_roles(session)

    client = app.test_client()
    client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )
    confirm_email(app, email)

    role_id = str(uuid.uuid4())
    with app.app_context():
        with app.container.get_db_manager().session() as session:
            session.execute(
                text(
                    "INSERT INTO roles (id, name, description, is_system) "
                    "VALUES (:id, :name, 'built for a test', 0)"
                ),
                {"id": role_id, "name": role_name},
            )
            for permission in permissions:
                row = session.execute(
                    text("SELECT id FROM permissions WHERE name = :name"),
                    {"name": permission},
                ).fetchone()
                assert row is not None, f"{permission} was never seeded"
                session.execute(
                    text(
                        "INSERT INTO role_permissions (role_id, permission_id) "
                        "VALUES (:role_id, :permission_id)"
                    ),
                    {"role_id": role_id, "permission_id": row[0]},
                )
            user = session.execute(
                text("SELECT id FROM users WHERE email = :email"),
                {"email": email},
            ).fetchone()
            assert user is not None, f"{email} was not registered"
            session.execute(
                text(
                    "INSERT INTO user_roles (user_id, role_id) "
                    "VALUES (:user_id, :role_id)"
                ),
                {"user_id": user[0], "role_id": role_id},
            )
            session.commit()

    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    token = response.get_json().get("access_token")
    assert token, f"{email} could not log in: {response.get_json()}"
    return client, token, user[0]


def arm_csrf(client, user_id):
    """
    Helper: give a bare client a CSRF token valid for a specific user.

    Used to drive a request that did not come from a login, such as replaying
    a stolen refresh token. Building the token rather than reusing a captured
    one keeps the test aimed at the behaviour under test instead of failing
    on the CSRF check.

    Args:
        client: Flask test client to arm.
        user_id: User the token should be bound to.

    Returns:
        Header dict containing ``X-CSRF-Token``.
    """
    token = build_csrf_token(IntegrationTestConfig.SECRET_KEY, user_id)
    client.set_cookie(CSRF_COOKIE_NAME, token, path="/")
    return {CSRF_HEADER_NAME: token}


def csrf_headers(client, extra=None):
    """
    Helper: build headers echoing the client's CSRF cookie, as a browser does.

    Args:
        client: Flask test client holding the session cookies.
        extra: Additional headers to merge in.

    Returns:
        Header dict including ``X-CSRF-Token`` when the cookie is present.
    """
    headers = dict(extra or {})
    cookie = client.get_cookie(CSRF_COOKIE_NAME)
    if cookie:
        headers[CSRF_HEADER_NAME] = cookie.value
    return headers


def ensure_user(session, user_id):
    """
    Insert a bare ``users`` row so a link may legally point at it.

    SQLite enforces foreign keys now, as PostgreSQL always has, so a test
    that files a link under an invented owner is writing a row production
    could not hold. Creating the account is what the test meant; leaving it
    out only worked because the constraint was asleep.

    Args:
        session: Active SQLAlchemy session.
        user_id: Identifier the link will name as its owner.
    """
    from link_shortener.infrastructure.database.models.user_model import (
        UserModel
    )

    if session.get(UserModel, user_id) is not None:
        return

    session.add(
        UserModel(
            id=user_id,
            email=f"{user_id}@fixture.invalid",
            password_hash="not-a-real-hash",
        )
    )
    session.flush()
