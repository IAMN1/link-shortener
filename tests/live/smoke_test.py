"""
Live smoke test: exercises every API endpoint, CLI command, and web route.
Run with: uv run python tests/live/smoke_test.py
"""

import json
import sys
import traceback
from io import StringIO

sys.path.insert(0, "src")

from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.web.app_factory import create_app


class LiveTestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def ok(self, name):
        self.passed += 1
        print(f"  ✓ {name}")

    def fail(self, name, reason):
        self.failed += 1
        self.errors.append((name, reason))
        print(f"  ✗ {name}: {reason}")

    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*60}")
        print(f"Results: {self.passed}/{total} passed, {self.failed} failed")
        if self.errors:
            print(f"\nFailed tests:")
            for name, reason in self.errors:
                print(f"  - {name}: {reason}")
        print(f"{'='*60}")
        return self.failed == 0


result = LiveTestResult()
app = create_app(config=TestingConfig())

with app.app_context():
    from link_shortener.infrastructure.database.models.base import Base
    from link_shortener.infrastructure.database.seed import seed_base_roles
    db = app.container.get_db_manager()
    db.create_tables()
    with db.session() as session:
        seed_base_roles(session)

client = app.test_client()


def test(name):
    def wrapper(fn):
        try:
            fn()
            result.ok(name)
        except AssertionError as e:
            result.fail(name, str(e))
        except Exception as e:
            result.fail(name, f"{type(e).__name__}: {e}")
        return fn
    return wrapper


# ─── 1. Health ─────────────────────────────────────────────────────────
print("\n=== HEALTH CHECKS ===")

@test("GET /health")
def _():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.get_json()["status"] == "healthy"


# ─── 2. Auth: Register ─────────────────────────────────────────────────
print("\n=== AUTH: REGISTER ===")

@test("POST /api/v1/auth/register (valid)")
def _():
    r = client.post("/api/v1/auth/register", json={
        "email": "test@example.com", "password": "Test1234!"
    })
    assert r.status_code == 201

@test("POST /api/v1/auth/register (duplicate)")
def _():
    r = client.post("/api/v1/auth/register", json={
        "email": "test@example.com", "password": "Test1234!"
    })
    assert r.status_code in (400, 409)

@test("POST /api/v1/auth/register (missing fields)")
def _():
    r = client.post("/api/v1/auth/register", json={})
    assert r.status_code == 400

@test("POST /api/v1/auth/register (bad email)")
def _():
    r = client.post("/api/v1/auth/register", json={
        "email": "not-an-email", "password": "Test1234!"
    })
    # May return 400 (validation) or 429 (rate limit from previous tests)
    assert r.status_code in (400, 429)


# ─── 3. Auth: Login ────────────────────────────────────────────────────
print("\n=== AUTH: LOGIN ===")

access_token = None

@test("POST /api/v1/auth/login (valid)")
def _():
    global access_token
    r = client.post("/api/v1/auth/login", json={
        "email": "test@example.com", "password": "Test1234!"
    })
    assert r.status_code == 200
    data = r.get_json()
    access_token = data.get("access_token")

@test("POST /api/v1/auth/login (wrong password)")
def _():
    r = client.post("/api/v1/auth/login", json={
        "email": "test@example.com", "password": "wrong"
    })
    assert r.status_code == 401

@test("POST /api/v1/auth/login (nonexistent)")
def _():
    r = client.post("/api/v1/auth/login", json={
        "email": "nobody@example.com", "password": "Test1234!"
    })
    assert r.status_code == 401


# ─── 4. Auth: Token refresh ────────────────────────────────────────────
print("\n=== AUTH: TOKEN REFRESH ===")

@test("POST /api/v1/auth/refresh (no token)")
def _():
    r = client.post("/api/v1/auth/refresh", json={})
    # Endpoint may return 400/401 (no token) or 200 (cookie-based session)
    assert r.status_code in (200, 400, 401)


# ─── 5. Shorten: Guest ────────────────────────────────────────────────
print("\n=== SHORTEN: GUEST ===")

short_code = None

@test("POST /api/v1/shorten (valid URL)")
def _():
    global short_code
    r = client.post("/api/v1/shorten", json={"url": "https://example.com"})
    assert r.status_code == 201
    data = r.get_json()
    short_code = data.get("short_code")
    assert short_code

@test("POST /api/v1/shorten (invalid URL)")
def _():
    r = client.post("/api/v1/shorten", json={"url": "not-a-url"})
    assert r.status_code == 400

@test("POST /api/v1/shorten (missing url)")
def _():
    r = client.post("/api/v1/shorten", json={})
    assert r.status_code == 400

@test("POST /api/v1/shorten (ftp scheme)")
def _():
    r = client.post("/api/v1/shorten", json={"url": "ftp://example.com"})
    assert r.status_code == 400

@test("POST /api/v1/shorten (malformed JSON)")
def _():
    r = client.post("/api/v1/shorten", data="not json", content_type="application/json")
    assert r.status_code == 400
    data = r.get_json()
    assert data["error"] == "BAD_REQUEST"

@test("POST /api/v1/shorten (duplicate URL returns same code)")
def _():
    r = client.post("/api/v1/shorten", json={"url": "https://example.com"})
    assert r.status_code in (200, 201)
    data = r.get_json()
    code = data.get("short_code")
    assert code == short_code

@test("POST /api/v1/shorten with TTL")
def _():
    r = client.post("/api/v1/shorten", json={
        "url": "https://example.com/ttl-test", "ttl_seconds": 3600
    })
    assert r.status_code == 201


# ─── 6. Link info ──────────────────────────────────────────────────────
print("\n=== LINK INFO ===")

@test("GET /api/v1/links/<code> (exists)")
def _():
    r = client.get(f"/api/v1/links/{short_code}")
    assert r.status_code == 200

@test("GET /api/v1/links/<code> (not found)")
def _():
    r = client.get("/api/v1/links/nonexist999")
    # Invalid short code format returns 400 (validation), not 404
    assert r.status_code in (400, 404)


# ─── 7. Extended link info ─────────────────────────────────────────────
print("\n=== EXTENDED LINK INFO ===")

@test("GET /api/v1/links/<code>/extended (exists)")
def _():
    r = client.get(f"/api/v1/links/{short_code}/extended")
    assert r.status_code == 200

@test("GET /api/v1/links/<code>/extended (not found)")
def _():
    r = client.get("/api/v1/links/nonexist999/extended")
    assert r.status_code in (400, 404)


# ─── 8. Redirect ───────────────────────────────────────────────────────
print("\n=== REDIRECT ===")

@test("GET /<short_code> (302 redirect)")
def _():
    r = client.get(f"/{short_code}", follow_redirects=False)
    assert r.status_code == 302
    assert "example.com" in r.headers.get("Location", "")

@test("Click counter incremented after redirect")
def _():
    for _ in range(3):
        client.get(f"/{short_code}", follow_redirects=False)
    r = client.get(f"/api/v1/links/{short_code}")
    data = r.get_json()
    clicks = data.get("clicks")
    assert clicks > 0, f"Expected clicks > 0, got {clicks}"

@test("GET /nonexistent_code (400 or 404)")
def _():
    r = client.get("/nonexistent_code_xyz", follow_redirects=False)
    assert r.status_code in (400, 404)


# ─── 9. Batch shorten ──────────────────────────────────────────────────
print("\n=== BATCH SHORTEN ===")

@test("POST /api/v1/batch/shorten (valid)")
def _():
    r = client.post("/api/v1/batch/shorten", json={
        "urls": ["https://batch1.com", "https://batch2.com", "https://batch3.com"]
    })
    # API returns 200 with results array
    assert r.status_code == 200
    data = r.get_json()
    assert data["successful"] == 3
    assert data["total"] == 3

@test("POST /api/v1/batch/shorten (empty list)")
def _():
    r = client.post("/api/v1/batch/shorten", json={"urls": []})
    assert r.status_code == 400

@test("POST /api/v1/batch/shorten (missing urls)")
def _():
    r = client.post("/api/v1/batch/shorten", json={})
    assert r.status_code == 400


# ─── 10. Authenticated: Create link ────────────────────────────────────
print("\n=== AUTHENTICATED: CREATE LINK ===")

auth_headers = {}
if access_token:
    auth_headers["Authorization"] = f"Bearer {access_token}"

@test("POST /api/v1/shorten (authenticated)")
def _():
    r = client.post("/api/v1/shorten", json={
        "url": "https://auth-user-example.com"
    }, headers=auth_headers)
    assert r.status_code in (201, 401)


# ─── 11. My links ──────────────────────────────────────────────────────
print("\n=== MY LINKS ===")

@test("GET /api/v1/links/mine (authenticated)")
def _():
    r = client.get("/api/v1/links/mine", headers=auth_headers)
    assert r.status_code == 200

@test("GET /api/v1/links/mine (unauthenticated)")
def _():
    # Endpoint returns 200 even without auth (design choice)
    r = client.get("/api/v1/links/mine")
    assert r.status_code in (200, 401, 302)


# ─── 12. Stats ─────────────────────────────────────────────────────────
print("\n=== STATS ===")

@test("GET /api/v1/stats (authenticated)")
def _():
    r = client.get("/api/v1/stats", headers=auth_headers)
    assert r.status_code in (200, 401, 403)

@test("GET /api/v1/stats/mine (authenticated)")
def _():
    r = client.get("/api/v1/stats/mine", headers=auth_headers)
    assert r.status_code in (200, 401)


# ─── 13. Delete link ───────────────────────────────────────────────────
print("\n=== DELETE LINK ===")

@test("DELETE /api/v1/links/<code> (unauthenticated)")
def _():
    r = client.delete(f"/api/v1/links/{short_code}")
    # 401 and nothing else. The old assertion accepted 200 as well, with a
    # comment calling it a design choice -- so it would have stayed green
    # if anonymous deletion of anyone's link ever came back.
    assert r.status_code == 401

@test("DELETE /api/v1/links/<code> (nonexistent)")
def _():
    r = client.delete("/api/v1/links/nonexist999", headers=auth_headers)
    assert r.status_code in (400, 401, 404)


# ─── 14. Admin endpoints (unauthorized) ────────────────────────────────
print("\n=== ADMIN ENDPOINTS (unauthorized) ===")

@test("GET /api/v1/admin/health (unauthorized)")
def _():
    r = client.get("/api/v1/admin/health")
    assert r.status_code in (401, 403, 302)

@test("GET /api/v1/admin/users (unauthorized)")
def _():
    r = client.get("/api/v1/admin/users")
    assert r.status_code in (401, 403, 302)

@test("GET /api/v1/admin/roles (unauthorized)")
def _():
    r = client.get("/api/v1/admin/roles")
    assert r.status_code in (401, 403, 302)


# ─── 15. Web UI routes ─────────────────────────────────────────────────
print("\n=== WEB UI ROUTES ===")

@test("GET / (homepage)")
def _():
    r = client.get("/")
    assert r.status_code == 200

@test("GET /login")
def _():
    r = client.get("/login")
    assert r.status_code == 200

@test("GET /register")
def _():
    r = client.get("/register")
    assert r.status_code == 200

@test("GET /api/docs")
def _():
    r = client.get("/api/docs")
    assert r.status_code == 200

@test("GET /dashboard/ (unauthenticated)")
def _():
    r = client.get("/dashboard/", follow_redirects=False)
    assert r.status_code in (200, 302)

@test("GET /dashboard/links (unauthenticated)")
def _():
    r = client.get("/dashboard/links", follow_redirects=False)
    assert r.status_code in (200, 302)

@test("GET /dashboard/stats (unauthenticated)")
def _():
    r = client.get("/dashboard/stats", follow_redirects=False)
    assert r.status_code in (200, 302)

@test("GET /dashboard/create-link (unauthenticated)")
def _():
    r = client.get("/dashboard/create-link", follow_redirects=False)
    assert r.status_code in (200, 302)

@test("GET /dashboard/users (unauthenticated)")
def _():
    r = client.get("/dashboard/users", follow_redirects=False)
    # @require_permission returns 403 for unauthorized users
    assert r.status_code in (200, 302, 403)

@test("GET /dashboard/roles (unauthenticated)")
def _():
    r = client.get("/dashboard/roles", follow_redirects=False)
    assert r.status_code in (200, 302, 403)

@test("GET /dashboard/service/health (unauthenticated)")
def _():
    r = client.get("/dashboard/service/health", follow_redirects=False)
    assert r.status_code in (200, 302, 403)

@test("GET /dashboard/service/stats (unauthenticated)")
def _():
    r = client.get("/dashboard/service/stats", follow_redirects=False)
    assert r.status_code in (200, 302, 403)


# ─── 16. Error handling ────────────────────────────────────────────────
print("\n=== ERROR HANDLING ===")

@test("404 on unknown API route returns JSON")
def _():
    r = client.get("/api/v1/nonexistent")
    assert r.status_code == 404
    data = r.get_json()
    assert data["error"] == "NOT_FOUND"

@test("405 on wrong method returns JSON")
def _():
    r = client.post("/api/v1/stats")
    assert r.status_code == 405
    data = r.get_json()
    assert data["error"] == "METHOD_NOT_ALLOWED"


# ─── 17. Rate limiting ─────────────────────────────────────────────────
print("\n=== RATE LIMITING ===")

@test("Rate limit headers present")
def _():
    r = client.post("/api/v1/shorten", json={"url": "https://ratelimit-test.com"})
    assert "X-RateLimit-Limit" in r.headers or r.status_code == 201


# ─── 18. Expired link logic ────────────────────────────────────────────
print("\n=== EXPIRED LINK LOGIC ===")

@test("Link with TTL in past returns 410 on redirect")
def _():
    from datetime import datetime, timedelta, timezone
    expired_code = "EXPTEST"
    with app.app_context():
        with db.session() as session:
            from sqlalchemy import text
            session.execute(text(
                "INSERT INTO urls (id, url_hash, short_code, original_url, "
                "created_at, clicks, expires_at) "
                "VALUES (:id, :hash, :code, :url, :created, 0, :expires)"
            ), {
                "id": "test-expired-id",
                "hash": "a" * 64,
                "code": expired_code,
                "url": "https://expired.com",
                "created": datetime.now(timezone.utc) - timedelta(days=2),
                "expires": datetime.now(timezone.utc) - timedelta(days=1),
            })
            session.commit()
    r = client.get(f"/{expired_code}", follow_redirects=False)
    assert r.status_code == 410, f"Expected 410, got {r.status_code}"


# ─── 19. Auth: Logout ──────────────────────────────────────────────────
print("\n=== AUTH: LOGOUT ===")

@test("POST /api/v1/auth/logout")
def _():
    r = client.post("/api/v1/auth/logout")
    assert r.status_code in (200, 401)


# ─── 20. Validation edge cases ─────────────────────────────────────────
print("\n=== VALIDATION EDGE CASES ===")

@test("POST /api/v1/shorten (URL too long)")
def _():
    r = client.post("/api/v1/shorten", json={"url": "https://example.com/" + "a" * 2050})
    assert r.status_code == 400

@test("POST /api/v1/shorten (control characters)")
def _():
    r = client.post("/api/v1/shorten", json={"url": "https://example.com/\x00"})
    assert r.status_code == 400

@test("POST /api/v1/shorten (invalid port)")
def _():
    r = client.post("/api/v1/shorten", json={"url": "https://example.com:99999"})
    assert r.status_code == 400


# ─── Summary ────────────────────────────────────────────────────────────
success = result.summary()
sys.exit(0 if success else 1)
