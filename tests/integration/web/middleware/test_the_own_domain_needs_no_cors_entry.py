"""Which origins a signed-in form may come from, and what decides it.

The CSRF layer refuses an unsafe cookie-authenticated request whose
`Origin` it does not recognise. The list it checks is `CORS_ORIGINS` **plus
`BASE_URL`**, added by `_allowed_origins` itself -- and that second half is
what nobody had written down.

Two documents drew the wrong conclusion from the first half alone. One is
`docs/configuration.md`, which described the mechanism without mentioning
`BASE_URL` at all. The other is a deployment guide kept beside the
repository rather than in it, so a reader here cannot check it: it told an
operator that `CORS_ORIGINS` had to name the deployment's own address or
"the form after sign-in answers CSRF token missing or invalid". Both were
written against the table below; this file is what keeps the table true.

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

import pytest
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


class TestBothSpellingsOfThisMachine:
    """
    A local run answers to two names, and a person types either.

    `.env.example` lists both spellings at port 5000 and says why: with
    `localhost` alone, "someone who opened `http://127.0.0.1:5000` sees a
    working front page ... and 'CSRF token missing or invalid' on every
    form the moment they sign in -- measured on a live run".

    That fix was pinned to a port. The guide tells a reader to move the
    published port when 5000 is taken, and moving it put the failure back:
    measured on a container stack published at 5101, every signed-in form
    at `http://127.0.0.1:5101` answered 403 `CSRF_TOKEN_INVALID` while the
    same form at `http://localhost:5101` answered 201 -- and the logout was
    refused the same way, silently, leaving the dashboard open to the next
    person at that browser. The two stale entries for 5000, where nothing
    was listening, were admitted throughout.

    So the twin is derived from `BASE_URL` rather than listed in a
    template: it follows the port instead of naming one.
    """

    def _loopback_app(self, tmp_path, port):
        """An app whose own address is loopback on `port`."""
        class Config(TestingConfig):
            pass

        Config.DOMAIN = None
        Config.USE_HTTPS = False
        Config.HOST = "localhost"
        Config.PORT = port
        Config.CORS_ORIGINS = []
        Config.MAIL_ENABLED = False
        Config.DATABASE_URL = f"sqlite:///{tmp_path}/twin.db"

        app = create_app(config=Config())
        with app.app_context():
            manager = app.container.get_db_manager()
            manager.create_tables()
            with manager.session() as session:
                seed_base_roles(session)
        return app

    @pytest.mark.parametrize("spelling", ["localhost", "127.0.0.1"])
    def test_a_form_is_accepted_from_either(self, tmp_path, spelling):
        app = self._loopback_app(tmp_path, 5101)
        _account(app)

        status = _form_after_sign_in(app, f"http://{spelling}:5101")

        assert status == 201, (
            f"a signed-in form from http://{spelling}:5101 was refused, "
            f"while the service answers on that very address"
        )

    def test_the_twin_follows_the_port(self, tmp_path):
        """
        The half that pinning to 5000 got wrong: the pair has to be the
        port actually published, not a port a template remembers.
        """
        app = self._loopback_app(tmp_path, 5101)
        _account(app)

        assert _form_after_sign_in(app, "http://127.0.0.1:5000") == 403

    def test_a_real_domain_gains_no_twin(self, tmp_path):
        """
        The other direction, and the one that matters for a deployment:
        this must not admit anything for a service that names a domain.
        """
        app = _app(tmp_path, cors_origins=[])
        _account(app)

        assert _form_after_sign_in(app, "http://127.0.0.1:5101") == 403
        assert _form_after_sign_in(app, OWN) == 201

    def test_a_host_that_merely_looks_loopback_gains_nothing(self):
        """
        `localhost.evil.example` is somebody else's domain. The twin is
        keyed on the whole host name, not on what it contains.
        """
        from link_shortener.web.middleware.csrf import (
            CsrfProtectionMiddleware
        )

        class Bare:
            config = {
                "CORS_ORIGINS": [],
                "BASE_URL": "https://localhost.evil.example",
            }

        admitted = CsrfProtectionMiddleware._build_allowed_origins(Bare())

        assert admitted == frozenset({"https://localhost.evil.example"})


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
