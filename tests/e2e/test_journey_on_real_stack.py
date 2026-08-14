"""A user's whole path, walked over real PostgreSQL and real Redis.

The other end-to-end tests run on in-memory SQLite with the cache switched
off. That is the fast pass, and it checks that the layers agree with each
other -- but not one thing about the software an operator actually
deploys: a link is written to PostgreSQL, served from Redis, and has to
disappear from both when it is deleted.

Three things here can only fail on the real stack:

* the redirect is answered out of Redis on the second call, so a cache
  that keeps a deleted link keeps serving it;
* the click counter survives the round trip to PostgreSQL rather than
  living in a process that the next request may not share;
* the refresh session is a row in a real database, so a logout has to
  reach it there.

Each test states what it is standing on -- the dialect and the cache class
are asserted before anything else -- because a fixture that quietly falls
back to SQLite would otherwise turn this file into a slower copy of its
neighbour.
"""

import pytest
from sqlalchemy import text

from link_shortener.domain.value_objects.short_code import ShortCode
from tests.integration.conftest import confirm_email, csrf_headers
from tests.support.real_stack import POSTGRES_URL, REDIS_URL

PASSWORD = "RealStackPass1!"
"""Meets the password policy the register endpoint enforces."""


@pytest.fixture(scope="module")
def app(real_stack):
    """An application wired to the real PostgreSQL and the real Redis.

    Caching is on, because half of what this stack is for is the cache: a
    redirect served from Redis, and a deletion that has to reach it, are
    invisible with a null implementation.
    """
    from link_shortener.infrastructure.configs.app.testing import TestingConfig
    from link_shortener.infrastructure.database.seed import seed_base_roles
    from link_shortener.web.app_factory import create_app

    class RealStackConfig(TestingConfig):
        DATABASE_URL = POSTGRES_URL
        DATABASE_TYPE = "postgresql"
        REDIS_ENABLED = True
        REDIS_URL = REDIS_URL
        CACHE_ENABLED = True
        CELERY_ENABLED = False
        LOGGING_ENABLED = False
        AUDIT_ENABLED = False
        AUTO_SEED_ROLES = False
        RATE_LIMIT_AUTH_DISABLED = True

    application = create_app(config=RealStackConfig())

    with application.app_context():
        manager = application.container.get_db_manager()
        manager.create_tables()
        with manager.session() as session:
            seed_base_roles(session)

    yield application

    with application.app_context():
        application.container.close()


@pytest.fixture()
def client(app):
    """A browser-shaped client, with its own cookie jar per test."""
    return app.test_client()


@pytest.fixture(autouse=True)
def _empty_between_tests(app):
    """Leave neither rows nor cache entries behind.

    Both halves matter and for the same reason this file exists: a test
    that truncates the tables but leaves Redis full hands the next one a
    cache that disagrees with the database.
    """
    yield

    with app.app_context():
        with app.container.get_db_manager().session() as session:
            session.execute(
                text(
                    "TRUNCATE urls, user_roles, role_permissions, users, "
                    "roles, permissions, refresh_sessions, "
                    "email_verifications CASCADE"
                )
            )
            session.commit()
        with app.container.get_db_manager().session() as session:
            from link_shortener.infrastructure.database.seed import seed_base_roles

            seed_base_roles(session)
        # Everything, not only the statistics entry: with the tables
        # truncated and Redis left full, a redirect to a link that no
        # longer exists is still answered 302 out of the cache -- measured,
        # not supposed. ``clear_all`` is on the implementations rather than
        # on the port, which is why this reaches past ``ServiceCache``.
        app.container.get_cache().clear_all()


def _register_and_sign_in(client, app, address):
    """Walk registration, confirmation and login; return auth headers."""
    response = client.post(
        "/api/v1/auth/register", json={"email": address, "password": PASSWORD}
    )
    assert response.status_code == 202, response.get_json()

    confirm_email(app, address)

    response = client.post(
        "/api/v1/auth/login", json={"email": address, "password": PASSWORD}
    )
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body


class TestTheStackUnderTest:
    """What this file is standing on, asserted rather than assumed."""

    def test_the_database_is_postgresql(self, app):
        """Not SQLite: the fixture would otherwise fall back silently."""
        with app.app_context():
            assert app.container.get_db_manager().engine.dialect.name == "postgresql"

    def test_the_cache_is_redis(self, app):
        """Not the null implementation, which accepts everything."""
        with app.app_context():
            assert type(app.container.get_cache()).__name__ == "RedisLinkCache"
            assert app.container.get_cache().ping() is True


class TestGuestJourney:
    """What an anonymous caller can do, end to end."""

    def test_a_link_is_stored_served_and_counted(self, client, app):
        """Shorten, redirect twice, and find the click in PostgreSQL."""
        response = client.post(
            "/api/v1/shorten", json={"url": "https://example.com/real-stack"}
        )
        assert response.status_code == 201, response.get_json()
        code = response.get_json()["short_code"]

        with app.app_context():
            with app.container.get_db_manager().session() as session:
                stored = session.execute(
                    text("SELECT original_url FROM urls WHERE short_code = :code"),
                    {"code": code},
                ).scalar_one()
        assert stored == "https://example.com/real-stack"

        first = client.get(f"/{code}", follow_redirects=False)
        assert first.status_code == 302
        assert first.headers["Location"] == "https://example.com/real-stack"

        second = client.get(f"/{code}", follow_redirects=False)
        assert second.status_code == 302

        with app.app_context():
            clicks = None
            for _ in range(20):
                with app.container.get_db_manager().session() as session:
                    clicks = session.execute(
                        text("SELECT clicks FROM urls WHERE short_code = :code"),
                        {"code": code},
                    ).scalar_one()
                if clicks >= 2:
                    break
        assert clicks >= 2, "both redirects should have reached the database"

    def test_the_second_redirect_is_answered_out_of_redis(self, client, app):
        """Take the row away, and the link still redirects.

        Checking that the cache holds an entry says nothing about who reads
        it: delete the lookup from the redirect path and the entry is still
        written, so that check passes over a service that never reads its
        cache. Deleting the row underneath is what makes the answer
        attributable -- after it, PostgreSQL cannot produce this redirect
        and Redis is the only thing left that can.

        Which of the two cache levels answered is deliberately not asserted.
        The redirect path tries L1 (the redirect entry) and falls back to L2
        (the link entry), and both live in the same Redis; pinning the level
        here would make this test fail when the levels are rearranged,
        which is a decision the unit tests of the use case already hold.
        """
        response = client.post(
            "/api/v1/shorten", json={"url": "https://example.com/from-redis"}
        )
        assert response.status_code == 201, response.get_json()
        code = response.get_json()["short_code"]

        assert client.get(f"/{code}", follow_redirects=False).status_code == 302

        with app.app_context():
            assert app.container.get_cache().get_redirect(ShortCode(code)) is not None
            with app.container.get_db_manager().session() as session:
                session.execute(
                    text("DELETE FROM urls WHERE short_code = :code"),
                    {"code": code},
                )
                session.commit()

        served = client.get(f"/{code}", follow_redirects=False)

        assert served.status_code == 302, "the row is gone; only Redis can answer"
        assert served.headers["Location"] == "https://example.com/from-redis"


class TestAccountJourney:
    """Registration, work, and signing out -- over the real stack."""

    def test_the_whole_path(self, client, app):
        """Register, confirm, sign in, create, list, delete, sign out."""
        headers, tokens = _register_and_sign_in(
            client, app, "journey-real@example.com"
        )

        response = client.post(
            "/api/v1/shorten",
            json={"url": "https://example.com/owned-link"},
            headers=headers,
        )
        assert response.status_code == 201, response.get_json()
        code = response.get_json()["short_code"]

        mine = client.get("/api/v1/links/mine", headers=headers)
        assert mine.status_code == 200
        assert any(
            link["short_code"] == code for link in mine.get_json()
        ), mine.get_json()

        stats = client.get("/api/v1/stats/mine", headers=headers)
        assert stats.status_code == 200
        assert stats.get_json()["total_links"] >= 1

        assert client.get(f"/{code}", follow_redirects=False).status_code == 302
        with app.app_context():
            assert app.container.get_cache().get_redirect(ShortCode(code)) is not None

        deleted = client.delete(
            f"/api/v1/links/{code}", headers=csrf_headers(client, headers)
        )
        assert deleted.status_code in (200, 204), deleted.get_json()

        # The point of doing this on the real stack: a deletion that reaches
        # PostgreSQL but not Redis leaves the link working.
        assert client.get(f"/{code}", follow_redirects=False).status_code == 404
        with app.app_context():
            assert app.container.get_cache().get_redirect(ShortCode(code)) is None
            with app.container.get_db_manager().session() as session:
                remaining = session.execute(
                    text("SELECT count(*) FROM urls WHERE short_code = :code"),
                    {"code": code},
                ).scalar_one()
        assert remaining == 0

        logout = client.post(
            "/api/v1/auth/logout", headers=csrf_headers(client, headers)
        )
        assert logout.status_code == 200

    def test_a_refresh_token_dies_with_the_session_row(self, client, app):
        """Signing out revokes the row, so the refresh token stops working."""
        headers, tokens = _register_and_sign_in(
            client, app, "refresh-real@example.com"
        )
        refresh_token = tokens["refresh_token"]

        with app.app_context():
            with app.container.get_db_manager().session() as session:
                live = session.execute(
                    text("SELECT count(*) FROM refresh_sessions")
                ).scalar_one()
        assert live == 1, "login should have written one session row"

        logout = client.post(
            "/api/v1/auth/logout", headers=csrf_headers(client, headers)
        )
        assert logout.status_code == 200

        refreshed = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
            headers=csrf_headers(client),
        )
        assert refreshed.status_code == 401, refreshed.get_json()
