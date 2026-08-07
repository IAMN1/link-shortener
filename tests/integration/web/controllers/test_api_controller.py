"""Integration tests for API controller endpoints with real DB."""

import pytest
from tests.integration.conftest import register_and_login, auth_headers



def _stored_clicks(app, code):
    """
    Read the click count from the database.

    Not from ``GET /api/v1/links/<code>``: that endpoint withholds the
    counter from callers who are not entitled to the link's traffic, and a
    guest link belongs to nobody. What these tests are about is whether the
    redirect increments the counter, so they ask the row.
    """
    from sqlalchemy import text

    with app.app_context():
        db = app.container.get_db_manager()
        with db.session() as session:
            row = session.execute(
                text("SELECT clicks FROM urls WHERE short_code=:c"), {"c": code}
            ).fetchone()
    return row[0] if row else 0

class TestShortenEndpoint:
    """POST /api/v1/shorten — full flow with real DB."""

    def test_create_short_link(self, client):
        r = client.post("/api/v1/shorten", json={"url": "https://example.com"})
        assert r.status_code == 201
        data = r.get_json()
        # `or "link" in data` stood here and named a key the response has
        # never carried, so the disjunction only ever tested the first half.
        assert "short_code" in data
        assert "short_url" in data

    def test_create_with_ttl(self, client):
        r = client.post("/api/v1/shorten", json={
            "url": "https://ttl-example.com", "ttl_seconds": 7200
        })
        assert r.status_code == 201

    def test_duplicate_returns_same_code(self, client):
        r1 = client.post("/api/v1/shorten", json={"url": "https://dup.com"})
        r2 = client.post("/api/v1/shorten", json={"url": "https://dup.com"})
        assert r1.status_code == 201
        assert r2.status_code == 200
        d1 = r1.get_json()
        d2 = r2.get_json()
        c1 = d1.get("short_code")
        c2 = d2.get("short_code")
        assert c1 == c2

    def test_invalid_url_returns_400(self, client):
        r = client.post("/api/v1/shorten", json={"url": "not-a-url"})
        assert r.status_code == 400

    def test_missing_url_returns_400(self, client):
        r = client.post("/api/v1/shorten", json={})
        assert r.status_code == 400

    def test_malformed_json_returns_400(self, client):
        r = client.post("/api/v1/shorten", data="bad", content_type="application/json")
        assert r.status_code == 400
        assert r.get_json()["error"] == "BAD_REQUEST"

    def test_ftp_scheme_rejected(self, client):
        r = client.post("/api/v1/shorten", json={"url": "ftp://files.com"})
        assert r.status_code == 400

    def test_url_too_long_rejected(self, client):
        r = client.post("/api/v1/shorten", json={"url": "https://x.com/" + "a" * 2050})
        assert r.status_code == 400


class TestLinkInfoEndpoint:
    """GET /api/v1/links/<code> — retrieve link info."""

    def _create(self, client):
        r = client.post("/api/v1/shorten", json={"url": "https://info-test.com"})
        data = r.get_json()
        return data.get("short_code")

    def test_get_existing_link(self, client):
        code = self._create(client)
        r = client.get(f"/api/v1/links/{code}")
        assert r.status_code == 200

    def test_get_nonexistent_returns_error(self, client):
        r = client.get("/api/v1/links/nonexist999")
        assert r.status_code == 404


class TestRedirectEndpoint:
    """GET /<short_code> — redirect to original URL."""

    def _create(self, client):
        r = client.post("/api/v1/shorten", json={"url": "https://redirect-test.com"})
        data = r.get_json()
        return data.get("short_code")

    def test_redirect_302(self, client):
        code = self._create(client)
        r = client.get(f"/{code}", follow_redirects=False)
        assert r.status_code == 302
        assert "redirect-test.com" in r.headers.get("Location", "")

    def test_click_counter_increments(self, app, client):
        code = self._create(client)
        for _ in range(5):
            client.get(f"/{code}", follow_redirects=False)

        assert _stored_clicks(app, code) >= 5

    def test_the_counter_is_not_public(self, client):
        """A guest link belongs to nobody, so nobody unentitled sees it."""
        code = self._create(client)
        client.get(f"/{code}", follow_redirects=False)

        data = client.get(f"/api/v1/links/{code}").get_json()

        assert data["clicks"] is None
        assert data["last_accessed"] is None

    def test_nonexistent_returns_404(self, client):
        r = client.get("/xyz999", follow_redirects=False)
        assert r.status_code == 404


class TestBatchEndpoint:
    """POST /api/v1/batch/shorten — batch creation."""

    def test_batch_create(self, client):
        r = client.post("/api/v1/batch/shorten", json={
            "urls": ["https://b1.com", "https://b2.com", "https://b3.com"]
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data["successful"] == 3
        assert data["total"] == 3

    def test_batch_empty_returns_400(self, client):
        r = client.post("/api/v1/batch/shorten", json={"urls": []})
        assert r.status_code == 400


class TestExpiredLink:
    """Expired links should return 410 on redirect."""

    def test_expired_link_returns_410(self, app, client):
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import text

        with app.app_context():
            db = app.container.get_db_manager()
            with db.session() as session:
                session.execute(text(
                    "INSERT INTO urls (id, url_hash, short_code, original_url, "
                    "created_at, clicks, expires_at) "
                    "VALUES (:id, :hash, :code, :url, :created, 0, :expires)"
                ), {
                    "id": "expired-int-test",
                    "hash": "b" * 64,
                    "code": "EXPINT",
                    "url": "https://expired-int.com",
                    "created": datetime.now(timezone.utc) - timedelta(days=2),
                    "expires": datetime.now(timezone.utc) - timedelta(hours=1),
                })
                session.commit()

        r = client.get("/EXPINT", follow_redirects=False)
        assert r.status_code == 410
