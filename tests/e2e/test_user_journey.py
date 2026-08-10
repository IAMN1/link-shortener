"""
E2E tests: complete user journeys through the full application.

Each test simulates a real user interaction from start to finish.
These tests verify that all layers work together correctly.
"""

import pytest

from tests.integration.conftest import confirm_email, csrf_headers


class TestGuestUserJourney:
    """Journey: anonymous user shortens a link and uses it."""

    def test_shorten_and_redirect(self, app, client):
        # 1. User visits homepage
        r = client.get("/")
        assert r.status_code == 200

        # 2. User shortens a URL
        r = client.post("/api/v1/shorten", json={"url": "https://example.com"})
        assert r.status_code == 201
        data = r.get_json()
        code = data.get("short_code")
        assert code is not None

        # 3. User checks link info
        r = client.get(f"/api/v1/links/{code}")
        assert r.status_code == 200

        # 4. User uses the short link (redirect)
        r = client.get(f"/{code}", follow_redirects=False)
        assert r.status_code == 302
        assert "example.com" in r.headers["Location"]

        # 5. Click counter is incremented. Read from the row: the public
        # endpoint withholds the counter from callers with no claim on the
        # link, and a guest link has no owner to make that claim.
        from sqlalchemy import text

        with app.app_context():
            db = app.container.get_db_manager()
            with db.session() as session:
                clicks = session.execute(
                    text("SELECT clicks FROM urls WHERE short_code=:c"),
                    {"c": code},
                ).fetchone()[0]
        assert clicks >= 1

    def test_batch_shorten(self, client):
        # 1. User shortens multiple URLs
        r = client.post("/api/v1/batch/shorten", json={
            "urls": ["https://a.com", "https://b.com", "https://c.com"]
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data["successful"] == 3

        # 2. Each link is redirectable
        for item in data["results"]:
            r = client.get(f"/{item['short_code']}", follow_redirects=False)
            assert r.status_code == 302


class TestRegisteredUserJourney:
    """Journey: user registers, creates links, manages them."""

    def test_register_create_manage(self, client):
        # 1. Register
        r = client.post("/api/v1/auth/register", json={
            "email": "journey@example.com", "password": "JourneyPass1!"
        })
        assert r.status_code == 201

        # 1a. Confirm the address. A real user opens the link that was
        # mailed to them; the suite sends no mail and keeps only the
        # token's digest, so the journey picks up where that link lands.
        confirm_email(client.application, "journey@example.com")

        # 2. Login
        r = client.post("/api/v1/auth/login", json={
            "email": "journey@example.com", "password": "JourneyPass1!"
        })
        assert r.status_code == 200
        token = r.get_json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 3. Create a link
        r = client.post("/api/v1/shorten", json={
            "url": "https://my-link.com"
        }, headers=headers)
        assert r.status_code == 201
        code = r.get_json().get("short_code")

        # 4. View my links
        r = client.get("/api/v1/links/mine", headers=headers)
        assert r.status_code == 200

        # 5. View my stats
        r = client.get("/api/v1/stats/mine", headers=headers)
        assert r.status_code == 200

        # 6. Redirect works
        r = client.get(f"/{code}", follow_redirects=False)
        assert r.status_code == 302

        # 7. Logout
        r = client.post("/api/v1/auth/logout", headers=csrf_headers(client, headers))
        assert r.status_code == 200


class TestDuplicateUrlJourney:
    """Journey: two users shorten the same URL."""

    def test_same_url_different_users(self, client):
        # 1. User A creates link
        r1 = client.post("/api/v1/shorten", json={"url": "https://shared.com"})
        assert r1.status_code == 201
        code1 = r1.get_json().get("short_code")

        # 2. User B creates link for same URL (guest with different IP)
        r2 = client.post("/api/v1/shorten", json={"url": "https://shared.com"})
        assert r2.status_code == 200
        code2 = r2.get_json().get("short_code")

        # 3. Both codes should be the same (deduplication)
        assert code1 == code2

        # 4. Redirect still works
        r = client.get(f"/{code1}", follow_redirects=False)
        assert r.status_code == 302


class TestExpiredLinkJourney:
    """Journey: link expires and is no longer accessible."""

    def test_expired_link_returns_410(self, app, client):
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import text

        # 1. Insert an already-expired link
        with app.app_context():
            db = app.container.get_db_manager()
            with db.session() as session:
                session.execute(text(
                    "INSERT INTO urls (id, url_hash, short_code, original_url, "
                    "created_at, clicks, expires_at) "
                    "VALUES (:id, :hash, :code, :url, :created, 0, :expires)"
                ), {
                    "id": "e2e-expired",
                    "hash": "c" * 64,
                    "code": "E2EEXP",
                    "url": "https://expired.com",
                    "created": datetime.now(timezone.utc) - timedelta(days=2),
                    "expires": datetime.now(timezone.utc) - timedelta(hours=1),
                })
                session.commit()

        # 2. Trying to access returns 410 Gone
        r = client.get("/E2EEXP", follow_redirects=False)
        assert r.status_code == 410


class TestErrorHandlingJourney:
    """Journey: user encounters various error conditions."""

    def test_invalid_url_returns_400(self, client):
        r = client.post("/api/v1/shorten", json={"url": "not-a-url"})
        assert r.status_code == 400
        data = r.get_json()
        assert "error" in data

    def test_malformed_json_returns_400(self, client):
        r = client.post("/api/v1/shorten", data="bad json", content_type="application/json")
        assert r.status_code == 400
        data = r.get_json()
        assert data["error"] == "BAD_REQUEST"

    def test_nonexistent_link_returns_404(self, client):
        r = client.get("/nonexistent")
        assert r.status_code == 404

    def test_wrong_method_returns_405(self, client):
        r = client.post("/api/v1/stats")
        assert r.status_code == 405

    def test_unauthorized_admin_returns_401(self, client):
        r = client.get("/api/v1/admin/health")
        assert r.status_code == 401


class TestHealthCheckJourney:
    """Journey: monitoring checks application health."""

    def test_health_endpoint(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.get_json()["status"] == "healthy"

    def test_health_after_operations(self, client):
        # Perform some operations
        client.post("/api/v1/shorten", json={"url": "https://health.com"})
        client.get("/health")
        r = client.get("/health")
        assert r.status_code == 200

    def test_the_probe_is_not_throttled(self, client):
        # Against the real app, so the endpoint name is the one the route
        # actually has. Renaming the view function renames the endpoint,
        # and the exemption is by endpoint name -- a rename that keeps the
        # path unchanged silently puts the probe back under the throttle.
        # The absence of the header is the tell: it is stamped only when a
        # limit was looked up, so one request settles it.
        r = client.get("/health")
        assert r.status_code == 200
        assert "X-RateLimit-Limit" not in r.headers
        assert "X-RateLimit-Remaining" not in r.headers

        # A missing header says "exempt" and "no throttle installed at all"
        # in exactly the same words. A throttled endpoint answering in the
        # same breath is what tells the two apart.
        throttled = client.get("/api/v1/stats")
        assert "X-RateLimit-Limit" in throttled.headers
