"""Which origins a signed-in form may come from, and what decides it.

The CSRF layer refuses an unsafe cookie-authenticated request whose
`Origin` it does not recognise. The list it checks is `CORS_ORIGINS` **plus
`BASE_URL`**, added by `_allowed_origins` itself -- and that second half is
what nobody had written down.

Two documents drew the wrong conclusion from the first half alone.
`DEMO-DEPLOY-GUIDE.md` told an operator that `CORS_ORIGINS` had to name the
deployment's own address or "the form after sign-in answers CSRF token
missing or invalid", and `docs/configuration.md` described the same
mechanism without mentioning `BASE_URL` at all. Both are now written
against the table below; this file is what keeps the table true.

The distinction matters in both directions. An operator who believes the
own address must be listed will list it -- harmless -- but will also read
the shipped `http://localhost:5000` as load-bearing and leave it in place,
which is an allowance for anybody's page on that port, with credentials.
An operator who believes nothing needs listing will be wrong the moment the
service answers on a second name.

Four rows, and each one is a different answer:

    DOMAIN=demo.example.com

    | visitor arrives at         | CORS_ORIGINS   | form after sign-in |
    | https://demo.example.com   | empty          | 201                |
    | https://demo.example.com   | names it       | 201                |
    | https://other.example.com  | empty          | 403                |
    | https://other.example.com  | names `other`  | 201                |

Sign-in itself is deliberately not the subject. It carries no session
cookie yet, so CSRF does not apply to it, and a check that stops at the
login page reports success for a configuration whose every later form is
refused. The request under test is the one *after* it.
"""

from sqlalchemy import text

from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.infrastructure.database.seed import seed_base_roles
from link_shortener.web.app_factory import create_app
from link_shortener.web.middleware.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME


DOMAIN = "demo.example.com"
OWN = f"https://{DOMAIN}"
OTHER = "https://other.example.com"


def _app(tmp_path, cors_origins):
    class Config(TestingConfig):
        pass

    Config.DOMAIN = DOMAIN
    Config.USE_HTTPS = True
    Config.CORS_ORIGINS = cors_origins
    Config.MAIL_ENABLED = False
    Config.DATABASE_URL = f"sqlite:///{tmp_path}/csrf.db"

    app = create_app(config=Config())
    with app.app_context():
        manager = app.container.get_db_manager()
        manager.create_tables()
        with manager.session() as session:
            seed_base_roles(session)
    return app


def _account(app):
    """Register and confirm one account, the way an operator without mail would."""
    with app.test_client() as client:
        client.post(
            "/api/v1/auth/register",
            json={"email": "visitor@example.com", "password": "Test1234!"},
        )
    with app.app_context():
        with app.container.get_db_manager().session() as session:
            session.execute(text("UPDATE users SET email_verified = true"))
            session.commit()


def _form_after_sign_in(app, origin):
    """Sign in, then post a form from `origin`. Returns that form's status."""
    with app.test_client() as client:
        signed_in = client.post(
            "/api/v1/auth/login",
            json={"email": "visitor@example.com", "password": "Test1234!"},
            headers={"Origin": origin},
        )
        assert signed_in.status_code == 200, (
            "sign-in itself failed, so this says nothing about the form: "
            f"{signed_in.get_data(as_text=True)[:200]}"
        )
        token = client.get_cookie(CSRF_COOKIE_NAME)
        assert token is not None, "signed in and holds no CSRF cookie"

        return client.post(
            "/api/v1/shorten",
            json={"url": "https://example.com/after-sign-in"},
            headers={CSRF_HEADER_NAME: token.value, "Origin": origin},
        ).status_code


class TestTheServicesOwnAddressNeedsNoEntry:
    """`BASE_URL` is admitted by the layer itself, so `DOMAIN` covers it."""

    def test_with_no_origin_named_at_all(self, tmp_path):
        app = _app(tmp_path, [])
        _account(app)

        assert _form_after_sign_in(app, OWN) == 201

    def test_and_naming_it_changes_nothing(self, tmp_path):
        app = _app(tmp_path, [OWN])
        _account(app)

        assert _form_after_sign_in(app, OWN) == 201


class TestAnyOtherAddressDoesNeedOne:
    """Which is what the list is for, and the only thing it is for."""

    def test_an_origin_that_is_not_the_domain_is_refused(self, tmp_path):
        app = _app(tmp_path, [])
        _account(app)

        assert _form_after_sign_in(app, OTHER) == 403

    def test_naming_it_admits_it(self, tmp_path):
        app = _app(tmp_path, [OTHER])
        _account(app)

        assert _form_after_sign_in(app, OTHER) == 201


class TestSignInIsNotTheCheck:
    """
    Stated as a check of its own because it is the trap: sign-in succeeds
    from an origin whose later forms are all refused, so "I logged in, it
    works" is not a verdict on this configuration.
    """

    def test_sign_in_succeeds_from_an_origin_whose_forms_are_refused(self, tmp_path):
        app = _app(tmp_path, [])
        _account(app)

        with app.test_client() as client:
            signed_in = client.post(
                "/api/v1/auth/login",
                json={"email": "visitor@example.com", "password": "Test1234!"},
                headers={"Origin": OTHER},
            )

        assert signed_in.status_code == 200
        assert _form_after_sign_in(app, OTHER) == 403
