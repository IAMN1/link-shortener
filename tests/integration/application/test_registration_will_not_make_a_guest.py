"""``DEFAULT_ROLE_NAME=guest`` registers nobody rather than registering guests.

``guest`` is the role an unauthenticated request acts under. An account
wearing it holds what a passer-by holds -- it signs in and the dashboard
it lands on refuses it -- so no account may be given it.

That rule was first put in ``UserManagementService``, on the reasoning
that the admin API, the panel and both CLI commands all reach an account
through it. Registration does not: it assembles the ``User`` itself.
Measured with the default role set to ``guest``: ``POST /auth/register``
answered 202 and the account was created holding ``guest``.

The rule is asked by ``User.create`` now, which is where a user first gets
roles whichever path built it, and by ``update_roles``, which is the one
path that goes around the factory.
"""

import pytest

from link_shortener.domain import Email
from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.infrastructure.database.seed import seed_base_roles
from link_shortener.web.app_factory import create_app


ADDRESS = "would-be-guest@example.test"
PASSWORD = "Str0ng!Passw0rd"


def _application(tmp_path, default_role):
    """Build an application whose default role is the given one."""
    class Config(TestingConfig):
        TESTING = True
        SECRET_KEY = "default-role-test-secret"
        SHORT_CODE_SECRET_PEPPER = "default-role-test-pepper"
        DATABASE_URL = f"sqlite:///{tmp_path}/{default_role}.db"
        REDIS_ENABLED = False
        CACHE_ENABLED = False
        LOGGING_ENABLED = False
        AUDIT_ENABLED = False
        AUTO_SEED_ROLES = False
        BASE_URL = "http://testserver/"
        HOST = "testserver"
        PORT = 80
        DEFAULT_ROLE_NAME = default_role

    built = create_app(config=Config())
    with built.app_context():
        db = built.container.get_db_manager()
        db.create_tables()
        with db.session() as session:
            seed_base_roles(session)
    return built


def _stored(application, address):
    """Read back the account, or ``None`` if there is none."""
    with application.app_context():
        factory = application.container.get_uow_factory()
        with factory(read_only=True) as uow:
            return uow.users.find_by_email(Email(address))


class TestADeploymentThatWouldRegisterGuests:
    """It registers nobody, and says so the way a missing role does."""

    @pytest.fixture()
    def application(self, tmp_path):
        return _application(tmp_path, "guest")

    def test_the_attempt_is_refused(self, application):
        answer = application.test_client().post(
            "/api/v1/auth/register",
            json={"email": ADDRESS, "password": PASSWORD},
        )

        assert answer.status_code == 400, answer.get_json()
        assert answer.get_json()["error"] == "REGISTRATION_UNAVAILABLE"

    def test_the_sentence_does_not_name_the_role(self, application):
        """An anonymous caller is not told which part is misconfigured.

        The same reason the missing-role branch beside it says nothing
        about which role is missing.
        """
        answer = application.test_client().post(
            "/api/v1/auth/register",
            json={"email": ADDRESS, "password": PASSWORD},
        )

        assert "guest" not in answer.get_json()["message"].lower()

    def test_no_account_is_left_behind(self, application):
        application.test_client().post(
            "/api/v1/auth/register",
            json={"email": ADDRESS, "password": PASSWORD},
        )

        assert _stored(application, ADDRESS) is None


class TestTheDeploymentEverybodyActuallyRuns:
    """The control: with the shipped default, registration works."""

    def test_an_ordinary_default_registers(self, tmp_path):
        application = _application(tmp_path, "user")

        answer = application.test_client().post(
            "/api/v1/auth/register",
            json={"email": ADDRESS, "password": PASSWORD},
        )

        assert answer.status_code == 202, answer.get_json()
        stored = _stored(application, ADDRESS)
        assert [role.name for role in stored.roles] == ["user"]


class TestAnAccountThatAlreadyWearsIt:
    """The rule stands at the door, not over the records already inside.

    A deployment upgraded into this rule has whatever accounts it had,
    and one of them may hold ``guest`` -- a default role set that way, or
    an assignment made before the rule existed. Refusing to *read* those
    would lock the holder out and take the admin list down with them, so
    ``User.create`` asks the rule and the repository's ``_to_domain``
    does not.
    """

    @pytest.fixture()
    def application(self, tmp_path):
        return _application(tmp_path, "user")

    def _account_wearing_guest(self, application):
        """Insert an account holding ``guest``, the way an older build would."""
        from sqlalchemy import text

        with application.app_context():
            auth = application.container.get_authentication_service()
            digest = auth.hash_password(PASSWORD)
            db = application.container.get_db_manager()
            with db.session() as session:
                session.execute(text(
                    "INSERT INTO users (id, email, password_hash, is_active, "
                    "email_verified, created_at) VALUES "
                    "('legacy-guest-1', :email, :hash, 1, 1, "
                    "'2026-01-01 00:00:00')"
                ), {"email": "legacy@example.test", "hash": digest})
                guest = session.execute(
                    text("SELECT id FROM roles WHERE name='guest'")
                ).fetchone()
                session.execute(text(
                    "INSERT INTO user_roles (user_id, role_id) "
                    "VALUES ('legacy-guest-1', :rid)"
                ), {"rid": guest[0]})
                session.commit()

    def test_it_is_still_readable(self, application):
        self._account_wearing_guest(application)

        stored = _stored(application, "legacy@example.test")

        assert stored is not None
        assert [role.name for role in stored.roles] == ["guest"]

    def test_it_can_still_sign_in(self, application):
        """Locking the holder out would be the upgrade breaking accounts."""
        self._account_wearing_guest(application)

        answer = application.test_client().post(
            "/api/v1/auth/login",
            json={"email": "legacy@example.test", "password": PASSWORD},
        )

        assert answer.status_code == 200, answer.get_json()
