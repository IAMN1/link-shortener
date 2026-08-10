"""
Live smoke test over the public surface of the running application.
Run with: uv run python tests/live/smoke_test.py

It covers what an anonymous caller, a programmatic client, a browser
session and an administrator can reach: every route rule the application
registers except `/static`, which is Flask's own. The number is not
maintained by hand -- the run records which rule answered each request and
fails if one was never reached.

The administrator is made the way an operator makes the first one, by
writing the role onto an account (`promote_to_admin`): there is no endpoint
for it and should not be, since the first administrator cannot be appointed
by an administrator.

Five clients, because one cannot stand for five callers. A Flask test
client keeps a cookie jar, so the moment any request on it logs in, every
later request on that client is a cookie-authenticated one -- and the CSRF
layer refuses unsafe cookie-authenticated requests that carry no token,
before the request reaches any logic. A single shared client therefore
turned every later POST and DELETE into 403 and, worse, turned each
"anonymous" check into a check on a signed-in caller.

  - ``guest``    never authenticates. It is what an anonymous caller is.
  - ``api``      authenticates with ``Authorization: Bearer`` and holds no
                 cookies, which is what a programmatic client is. CSRF does
                 not apply to it, by design.
  - ``session``  logs in and keeps the cookies, which is what a browser is.
                 Every unsafe request on it goes through ``csrf()``.
  - ``admin``    an account with the admin role, written straight into
                 the database the way an operator makes the first one.
  - ``stranger`` a second account, logged in and entitled to nothing here.
                 Without it the file has only an owner and an anonymous
                 caller, and every per-object authorization check could be
                 deleted from the application with this run still green:
                 "logged in, but not yours" is a third answer, and it is
                 the one those checks exist to give.

Every client answers from an address of its own, and the checks that measure
a quota get a fresh one. The guest quota counts per address throughout; the
rate limiter counts per address only while the caller is anonymous and
switches to the account once one is signed in, so `session_client` and
`api` share a bucket whatever addresses they claim. Sharing an address made
each check the neighbour of every check that happened to precede it:
registrations are three per hour, and the fourth scenario used to measure
the throttle rather than what it was named after.
"""

import re
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from flask import request

from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.web.app_factory import create_app
from link_shortener.web.middleware.csrf import (
    CSRF_COOKIE_NAME, CSRF_HEADER_NAME, build_csrf_token
)


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
            print("\nFailed tests:")
            for name, reason in self.errors:
                print(f"  - {name}: {reason}")
        print(f"{'='*60}")
        return self.failed == 0


result = LiveTestResult()
app = create_app(config=TestingConfig())

touched_rules = set()


@app.after_request
def _record_the_rule_that_answered(response):
    """
    Note which route rule answered, so coverage is counted not claimed.

    The file used to say in its own docstring how many routes it reached.
    That number was maintained by hand and had no way of noticing a check
    being deleted, renamed, or quietly pointed somewhere else.

    Args:
        response: The response about to be returned.

    Returns:
        The response, untouched.
    """
    if request.url_rule is not None:
        touched_rules.add(str(request.url_rule))
    return response

with app.app_context():
    from link_shortener.infrastructure.database.seed import seed_base_roles
    db = app.container.get_db_manager()
    db.create_tables()
    with db.session() as session:
        seed_base_roles(session)


def new_client(ip: str = "127.0.0.1"):
    """
    Build a test client that presents itself from a chosen address.

    The address is what the guest quota and the rate limiter count against,
    so a scenario that must not share a quota with its neighbours asks for
    its own.

    Args:
        ip: Value to report as ``REMOTE_ADDR``.

    Returns:
        A Flask test client with an empty cookie jar.
    """
    client = app.test_client()
    client.environ_base = dict(client.environ_base)
    client.environ_base["REMOTE_ADDR"] = ip
    return client


def csrf(client, extra: dict = None) -> dict:
    """
    Echo a cookie-bearing client's CSRF token in a header, as a browser does.

    Refuses to build headers for a client that holds no token rather than
    quietly omitting it: a missing header is answered with 403 before the
    request reaches any logic, which would turn a check on the endpoint into
    a check on the CSRF layer without saying so.

    Args:
        client: Test client holding the session cookies.
        extra: Additional headers to merge in.

    Returns:
        Header dict including ``X-CSRF-Token``.

    Raises:
        AssertionError: If the client holds no CSRF cookie.
    """
    cookie = client.get_cookie(CSRF_COOKIE_NAME)
    assert cookie is not None, "client holds no CSRF cookie -- did it log in?"
    headers = dict(extra or {})
    headers[CSRF_HEADER_NAME] = cookie.value
    return headers


def lifetime(link: dict) -> float:
    """
    Seconds between a link's creation and its expiry.

    Args:
        link: A decoded ShortLinkResponse body.

    Returns:
        The link's lifetime in seconds.
    """
    created = datetime.fromisoformat(link["created_at"])
    expires = datetime.fromisoformat(link["expires_at"])
    return (expires - created).total_seconds()


def _detail(error: BaseException) -> str:
    """
    Describe a failure by the line that raised it.

    A bare ``assert`` carries no message, so reporting ``str(e)`` alone
    printed the name of the check followed by nothing at all.

    Args:
        error: The exception that ended the check.

    Returns:
        Source line and line number, plus the exception's own text if any.
    """
    frame = traceback.extract_tb(error.__traceback__)[-1]
    said = str(error)
    where = f"{frame.line}  [line {frame.lineno}]"
    return f"{where} -- {said}" if said else where


def test(name):
    def wrapper(fn):
        try:
            fn()
            result.ok(name)
        except AssertionError as e:
            result.fail(name, _detail(e))
        # SystemExit is not an Exception. Raised out of application code it
        # would end the run carrying whatever status it liked, skipping the
        # summary and the exit code below -- a failure reporting success.
        # KeyboardInterrupt is deliberately left to propagate.
        except (Exception, SystemExit) as e:
            result.fail(name, f"{type(e).__name__}: {_detail(e)}")
        return fn
    return wrapper


guest = new_client("127.0.0.1")
session_client = new_client("127.0.0.2")
api = new_client("127.0.0.3")
stranger = new_client("127.0.0.4")
admin = new_client("127.0.0.5")


def promote_to_admin(email: str) -> None:
    """
    Give an account the admin role, the way an operator would.

    There is no endpoint for this and there should not be: the first
    administrator cannot be made by an administrator. The row is written
    directly, which is what `flask db` does and what the deployment notes
    tell an operator to do.

    Args:
        email: Address of the account to promote.
    """
    from sqlalchemy import text

    with app.app_context():
        db = app.container.get_db_manager()
        with db.session() as session:
            user = session.execute(
                text("SELECT id FROM users WHERE email = :email"),
                {"email": email},
            ).fetchone()
            role = session.execute(
                text("SELECT id FROM roles WHERE name = 'admin'")
            ).fetchone()
            assert user is not None, f"no account for {email}"
            assert role is not None, "the admin role was never seeded"
            session.execute(
                text(
                    "INSERT OR IGNORE INTO user_roles (user_id, role_id) "
                    "VALUES (:uid, :rid)"
                ),
                {"uid": user[0], "rid": role[0]},
            )
            session.commit()

GUEST_URL = "https://example.com"
OWNED_URL = "https://auth-user-example.com"
BROWSER_URL = "https://browser-session-example.com"

SHORT_CODE = re.compile(r"^[A-Za-z0-9_-]{6,10}$")
"""The shape the OpenAPI document promises for a short code."""


# ─── 1. Health ─────────────────────────────────────────────────────────
print("\n=== HEALTH CHECKS ===")

@test("GET /health")
def _():
    r = guest.get("/health")
    assert r.status_code == 200
    data = r.get_json()
    assert data["status"] == "healthy"
    # "healthy" is a summary of these, and one of them is a premise several
    # later checks rest on: with the throttle degraded, the quota
    # assertions below would be measuring nothing. "cache: disabled" names
    # the absence of a cache server, not the absence of a cache -- an
    # in-memory one is running, which is what section 12 invalidates.
    assert data["components"] == {
        "cache": "disabled",
        "database": "ok",
        "rate_limiter": "enforcing",
        "task_queue": "ok",
    }

@test("GET /health (never throttled)")
def _():
    # The probe is how the orchestrator learns whether this instance is
    # alive, and a 429 is indistinguishable from a real failure to it.
    #
    # The missing header is what settles this, not the twelve requests.
    # The exemption returns before any limit is looked up, so not even the
    # default of a hundred per minute applies here and twelve outrun
    # nothing. The header is stamped only where a limit was looked up, so
    # its absence is the whole answer.
    for _ in range(12):
        r = guest.get("/health")
        assert r.status_code == 200
    assert "X-RateLimit-Limit" not in r.headers


# ─── 2. Auth: Register ─────────────────────────────────────────────────
print("\n=== AUTH: REGISTER ===")

@test("POST /api/v1/auth/register (valid)")
def _():
    r = new_client("10.0.0.1").post("/api/v1/auth/register", json={
        "email": "test@example.com", "password": "Test1234!"
    })
    assert r.status_code == 201
    assert r.get_json()["user"]["roles"] == ["user"]

@test("POST /api/v1/auth/register (duplicate)")
def _():
    r = new_client("10.0.0.2").post("/api/v1/auth/register", json={
        "email": "test@example.com", "password": "Test1234!"
    })
    assert r.status_code == 400
    body = r.get_json()
    assert body["error"] == "VALIDATION_ERROR"
    assert body["message"] == "Email already registered"

@test("POST /api/v1/auth/register (missing fields)")
def _():
    r = new_client("10.0.0.3").post("/api/v1/auth/register", json={})
    assert r.status_code == 400

@test("POST /api/v1/auth/register (bad email)")
def _():
    r = new_client("10.0.0.4").post("/api/v1/auth/register", json={
        "email": "not-an-email", "password": "Test1234!"
    })
    assert r.status_code == 400
    body = r.get_json()
    assert body["error"] == "VALIDATION_ERROR"
    assert body["message"] == "Invalid email format"

@test("POST /api/v1/auth/register (fourth attempt from one address)")
def _():
    # Three per hour per address. Asserted here so that the four checks
    # above may each be about their own subject rather than about whichever
    # of them the throttle happened to reach first.
    throttled = new_client("10.0.0.9")
    for i in range(3):
        r = throttled.post("/api/v1/auth/register", json={
            "email": f"burst{i}@example.com", "password": "Test1234!"
        })
        assert r.status_code == 201, f"attempt {i} was refused"
    r = throttled.post("/api/v1/auth/register", json={
        "email": "burst3@example.com", "password": "Test1234!"
    })
    assert r.status_code == 429
    assert r.get_json()["error"] == "RATE_LIMIT_EXCEEDED"


# ─── 3. Auth: Login ────────────────────────────────────────────────────
print("\n=== AUTH: LOGIN ===")

access_token = None
user_id = None
stranger_token = None
stranger_id = None

@test("POST /api/v1/auth/login (valid)")
def _():
    global access_token, user_id
    r = session_client.post("/api/v1/auth/login", json={
        "email": "test@example.com", "password": "Test1234!"
    })
    assert r.status_code == 200
    data = r.get_json()
    assert data["user"]["email"] == "test@example.com"
    assert data["user"]["is_active"] is True
    access_token = data["access_token"]
    user_id = data["user"]["id"]
    assert access_token
    # Login is where a browser session gets the token every later write
    # has to echo. Without it the session is stranded in 403.
    assert session_client.get_cookie(CSRF_COOKIE_NAME) is not None

@test("POST /api/v1/auth/login (cookie flags)")
def _():
    # Read off the wire, not out of the jar: the test client's cookie jar
    # hands back HttpOnly cookies just the same, so nothing that goes
    # through it can tell a protected cookie from an exposed one.
    r = new_client("10.0.0.5").post("/api/v1/auth/login", json={
        "email": "test@example.com", "password": "Test1234!"
    })
    assert r.status_code == 200
    flags = {
        header.split("=", 1)[0]: header
        for header in r.headers.getlist("Set-Cookie")
    }
    assert set(flags) == {"access_token", "refresh_token", "csrf_token"}
    for name in ("access_token", "refresh_token"):
        assert "HttpOnly" in flags[name], name
        assert "SameSite=Strict" in flags[name], name
    # Deliberately readable: the frontend has to read this one to build the
    # header it echoes. HttpOnly here would break every real browser while
    # leaving this file green.
    assert "HttpOnly" not in flags["csrf_token"]
    assert "SameSite=Strict" in flags["csrf_token"]

@test("POST /api/v1/auth/login (wrong password)")
def _():
    r = guest.post("/api/v1/auth/login", json={
        "email": "test@example.com", "password": "wrong"
    })
    assert r.status_code == 401

@test("POST /api/v1/auth/login (nonexistent)")
def _():
    r = guest.post("/api/v1/auth/login", json={
        "email": "nobody@example.com", "password": "Test1234!"
    })
    assert r.status_code == 401
    # Word for word what a wrong password gets. The two are kept
    # indistinguishable on purpose, so that this endpoint cannot be asked
    # whether an address has an account. Everything but the envelope's
    # timestamp, which is stamped per answer and says nothing about the
    # account.
    body = r.get_json()
    assert body["error"] == "INVALID_CREDENTIALS"
    assert body["message"] == "Invalid email or password"
    assert body["details"] is None

@test("A second account, entitled to nothing of the first's")
def _():
    global stranger_token, stranger_id
    r = stranger.post("/api/v1/auth/register", json={
        "email": "stranger@example.com", "password": "Test1234!"
    })
    assert r.status_code == 201
    r = stranger.post("/api/v1/auth/login", json={
        "email": "stranger@example.com", "password": "Test1234!"
    })
    assert r.status_code == 200
    data = r.get_json()
    assert data["user"]["roles"] == ["user"]
    assert data["user"]["id"] != user_id
    stranger_token = data["access_token"]
    stranger_id = data["user"]["id"]


# ─── 4. Auth: Token refresh ────────────────────────────────────────────
print("\n=== AUTH: TOKEN REFRESH ===")

@test("POST /api/v1/auth/refresh (no token)")
def _():
    r = guest.post("/api/v1/auth/refresh", json={})
    assert r.status_code == 401

@test("POST /api/v1/auth/refresh (browser session)")
def _():
    spent = session_client.get_cookie("refresh_token").value
    r = session_client.post("/api/v1/auth/refresh", json={},
                            headers=csrf(session_client))
    assert r.status_code == 200
    # Rotation is the point of the endpoint: the old refresh token is spent
    # and would be read as a replay, so the cookie has to carry the new one.
    # Asserting the access token is merely present would not see that --
    # two access tokens minted in the same second are byte-identical anyway.
    assert session_client.get_cookie("refresh_token").value != spent
    assert r.get_json()["refresh_token"] != spent

@test("POST /api/v1/auth/refresh (token in the body)")
def _():
    # The documented path for a client with no cookie jar, and the only one
    # the `api` client could ever use. It is reached by a different branch
    # from the cookie path and was covered by neither check above.
    signed_in = new_client("10.0.0.6")
    handed_out = signed_in.post("/api/v1/auth/login", json={
        "email": "test@example.com", "password": "Test1234!"
    }).get_json()["refresh_token"]
    bare = new_client("10.0.0.7")
    r = bare.post("/api/v1/auth/refresh", json={"refresh_token": handed_out})
    assert r.status_code == 200
    assert r.get_json()["refresh_token"] != handed_out


# ─── 5. Shorten: Guest ────────────────────────────────────────────────
print("\n=== SHORTEN: GUEST ===")

short_code = None
deletion_token = None

@test("POST /api/v1/shorten (valid URL)")
def _():
    global short_code, deletion_token
    r = guest.post("/api/v1/shorten", json={"url": GUEST_URL})
    assert r.status_code == 201
    data = r.get_json()
    short_code = data["short_code"]
    assert SHORT_CODE.match(short_code), short_code
    assert data["short_url"].endswith(f"/{short_code}")
    assert data["owner_id"] is None
    # A guest link is not permanent: seven days, unasked.
    assert lifetime(data) == 7 * 24 * 3600
    # A guest link has no owner to prove anything against, so the token
    # returned here is the only handle its creator will ever have on it.
    deletion_token = data["deletion_token"]
    assert deletion_token

@test("POST /api/v1/shorten (invalid URL)")
def _():
    r = guest.post("/api/v1/shorten", json={"url": "not-a-url"})
    assert r.status_code == 400
    # 400 alone cannot tell one refusal from another, and these three reach
    # it for three different reasons. The message is what says which.
    assert r.get_json()["message"] == "URL must have a scheme!"

@test("POST /api/v1/shorten (missing url)")
def _():
    r = guest.post("/api/v1/shorten", json={})
    assert r.status_code == 400
    assert r.get_json()["message"] == "Request validation failed"

@test("POST /api/v1/shorten (ftp scheme)")
def _():
    r = guest.post("/api/v1/shorten", json={"url": "ftp://example.com"})
    assert r.status_code == 400
    assert r.get_json()["message"] == (
        "Scheme 'ftp' is not allowed. Allowed schemes: http, https"
    )

@test("POST /api/v1/shorten (malformed JSON)")
def _():
    r = guest.post("/api/v1/shorten", data="not json",
                   content_type="application/json")
    assert r.status_code == 400
    assert r.get_json()["error"] == "BAD_REQUEST"

@test("POST /api/v1/shorten (duplicate URL returns same code)")
def _():
    r = guest.post("/api/v1/shorten", json={"url": GUEST_URL})
    # 200, not 201: an existing link is not a created one, and the two
    # statuses are the only thing telling the caller which happened.
    assert r.status_code == 200
    data = r.get_json()
    assert data["short_code"] == short_code
    assert data["is_new"] is False
    # Issued once, to whoever created the row. Guests deduplicate by
    # address, so handing it out again would hand the first guest's link to
    # the next caller behind the same NAT.
    assert data["deletion_token"] is None

@test("POST /api/v1/shorten with TTL")
def _():
    r = guest.post("/api/v1/shorten", json={
        "url": "https://example.com/ttl-test", "ttl_seconds": 3600
    })
    assert r.status_code == 201
    # The hour asked for, not merely some expiry: a guest link gets seven
    # days by default, so "expires_at is not None" held even when the
    # ttl_seconds field was ignored entirely.
    assert lifetime(r.get_json()) == 3600


# ─── 6. Link info ──────────────────────────────────────────────────────
print("\n=== LINK INFO ===")

@test("GET /api/v1/links/<code> (exists)")
def _():
    r = guest.get(f"/api/v1/links/{short_code}")
    assert r.status_code == 200
    data = r.get_json()
    assert data["short_code"] == short_code
    assert data["original_url"] == GUEST_URL

@test("GET /api/v1/links/<code> (counters withheld from an anonymous caller)")
def _():
    r = guest.get(f"/api/v1/links/{short_code}")
    data = r.get_json()
    # Not a number: a seven-character code is guessable, so the traffic and
    # the owner behind one are shown to the owner, an admin, or a holder of
    # stats:view_any, and to nobody else. Only `clicks` carries weight here
    # -- this is a guest link that has not been followed, so the other two
    # are None in the row as well. Section 11 asks the same question of a
    # link that has all three, as somebody who is not entitled to them.
    assert data["clicks"] is None
    assert data["last_accessed"] is None
    assert data["owner_id"] is None

@test("GET /api/v1/links/<code> (not found)")
def _():
    r = guest.get("/api/v1/links/nonexist999")
    assert r.status_code == 404
    assert r.get_json()["error"] == "LINK_NOT_FOUND"


# ─── 7. Extended link info ─────────────────────────────────────────────
print("\n=== EXTENDED LINK INFO ===")

@test("GET /api/v1/links/<code>/extended (anonymous)")
def _():
    # Every field here is computed from the counters the basic endpoint
    # withholds, so an anonymous caller is refused rather than handed the
    # same numbers by a different name.
    r = guest.get(f"/api/v1/links/{short_code}/extended")
    assert r.status_code == 401
    assert r.get_json()["error"] == "UNAUTHENTICATED"

@test("GET /api/v1/links/<code>/extended (not found)")
def _():
    r = guest.get("/api/v1/links/nonexist999/extended")
    assert r.status_code == 404


# ─── 8. Redirect ───────────────────────────────────────────────────────
print("\n=== REDIRECT ===")

@test("GET /<short_code> (302 redirect)")
def _():
    r = guest.get(f"/{short_code}", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"] == GUEST_URL

@test("GET /nonexistent_code (404)")
def _():
    r = guest.get("/nonexistent_code_xyz", follow_redirects=False)
    assert r.status_code == 404


# ─── 9. Batch shorten ──────────────────────────────────────────────────
print("\n=== BATCH SHORTEN ===")

batch_items = []

@test("POST /api/v1/batch/shorten (valid)")
def _():
    r = guest.post("/api/v1/batch/shorten", json={
        "urls": ["https://batch1.com", "https://batch2.com",
                 "https://batch3.com"]
    })
    # 200 with a results array: some items may fail while others do not,
    # so the status describes the batch, not any one link.
    #
    # Three of the five requests a minute this endpoint allows one address.
    # A fourth batch check here is fine; a sixth would surface as a 429 in
    # whichever of these three came last, naming the wrong subject.
    assert r.status_code == 200
    data = r.get_json()
    assert data["successful"] == 3
    assert data["total"] == 3
    assert data["failed"] == 0
    # The same claim a single guest link comes with, for the same reason:
    # a guest who shortens three at once has the same hold on them as a
    # guest who shortens one. Section 13 spends two of these.
    assert all(item["deletion_token"] for item in data["results"])
    assert all(SHORT_CODE.match(item["short_code"]) for item in data["results"])
    batch_items.extend(data["results"])

@test("POST /api/v1/batch/shorten (empty list)")
def _():
    r = guest.post("/api/v1/batch/shorten", json={"urls": []})
    assert r.status_code == 400

@test("POST /api/v1/batch/shorten (missing urls)")
def _():
    r = guest.post("/api/v1/batch/shorten", json={})
    assert r.status_code == 400


# ─── 10. Authenticated: Create link ────────────────────────────────────
print("\n=== AUTHENTICATED: CREATE LINK ===")

auth_headers = {}
owned_code = None
browser_code = None

@test("POST /api/v1/shorten (Bearer token)")
def _():
    global owned_code
    auth_headers["Authorization"] = f"Bearer {access_token}"
    r = api.post("/api/v1/shorten", json={"url": OWNED_URL},
                 headers=auth_headers)
    assert r.status_code == 201
    data = r.get_json()
    owned_code = data["short_code"]
    # Filed under the account that asked, not merely under somebody.
    assert data["owner_id"] == user_id
    # An account's link never expires; only a guest's is given a lifetime.
    assert data["expires_at"] is None
    # An owned link is deletable by its owner, so it needs no token -- and
    # handing one out would be a second key to somebody's account's link.
    assert data["deletion_token"] is None

@test("POST /api/v1/shorten (browser session, no CSRF token)")
def _():
    # The failure this whole file was rewritten for. The session cookies
    # alone are not enough: an unsafe request resting on them is refused
    # before it reaches the endpoint.
    r = session_client.post("/api/v1/shorten", json={"url": BROWSER_URL})
    assert r.status_code == 403
    assert r.get_json()["error"] == "CSRF_TOKEN_INVALID"

@test("POST /api/v1/shorten (browser session, with CSRF token)")
def _():
    global browser_code
    r = session_client.post("/api/v1/shorten", json={"url": BROWSER_URL},
                            headers=csrf(session_client))
    assert r.status_code == 201
    data = r.get_json()
    browser_code = data["short_code"]
    # The same account, reached by the other door.
    assert data["owner_id"] == user_id

@test("POST /api/v1/shorten (browser session, forged CSRF token)")
def _():
    # Cookie and header agree, so plain double submit is satisfied; the
    # signature is not. This is the leg that stops whoever can write a
    # cookie on the domain -- a script on a sibling subdomain, or anyone on
    # the wire while cookies travel unencrypted -- from planting a value
    # they know and posting it back to themselves. A token that only had to
    # match itself would leave every other check in this file green.
    #
    # The issue time is minted now, on purpose. Written as a constant it
    # went stale, and a token older than CSRF_TOKEN_TTL_SECONDS is refused
    # on its age before the signature is ever compared -- so this check
    # passed with the whole HMAC leg deleted from the application.
    forged = f"forged.{int(time.time())}.deadbeef"
    session_client.set_cookie(CSRF_COOKIE_NAME, forged, path="/")
    r = session_client.post("/api/v1/shorten",
                            json={"url": "https://forged.example"},
                            headers={CSRF_HEADER_NAME: forged})
    assert r.status_code == 403
    assert r.get_json()["error"] == "CSRF_TOKEN_INVALID"
    # The refusal reissues a token that does verify, so the session is not
    # stranded in 403 -- and the next check needs a working one.
    assert session_client.get_cookie(CSRF_COOKIE_NAME).value != forged

@test("POST /api/v1/shorten (browser session, another user's CSRF token)")
def _():
    # Signed by this service, unexpired, and issued to somebody else. The
    # token is bound to the owner of the cookies, so a caller who can mint
    # or steal a token of their own cannot spend it on a session that is
    # not theirs -- which is what the signature alone would allow.
    someone_else = build_csrf_token(TestingConfig.SECRET_KEY, stranger_id)
    session_client.set_cookie(CSRF_COOKIE_NAME, someone_else, path="/")
    r = session_client.post("/api/v1/shorten",
                            json={"url": "https://borrowed-token.example"},
                            headers={CSRF_HEADER_NAME: someone_else})
    assert r.status_code == 403
    assert r.get_json()["error"] == "CSRF_TOKEN_INVALID"
    assert session_client.get_cookie(CSRF_COOKIE_NAME).value != someone_else

@test("POST /api/v1/shorten (browser session, foreign Origin)")
def _():
    # A signed token that checks out, sent from somewhere we do not serve.
    # This is what stops the planted-cookie case from a sibling subdomain:
    # cookies do not distinguish subdomains, Origin does.
    r = session_client.post(
        "/api/v1/shorten", json={"url": "https://cross-origin.example"},
        headers=csrf(session_client, {"Origin": "https://evil.example.com"}),
    )
    assert r.status_code == 403
    assert r.get_json()["error"] == "CSRF_TOKEN_INVALID"


# ─── 11. Who may see a link's traffic ──────────────────────────────────
print("\n=== WHO MAY SEE A LINK'S TRAFFIC ===")

@test("Click counter incremented after redirect")
def _():
    for _ in range(3):
        r = api.get(f"/{owned_code}", follow_redirects=False)
        assert r.status_code == 302
    r = api.get(f"/api/v1/links/{owned_code}", headers=auth_headers)
    assert r.status_code == 200
    data = r.get_json()
    # Three redirects, three clicks. A floor ("> 0") would pass on a
    # counter that stopped at one.
    assert data["clicks"] == 3
    assert data["last_accessed"] is not None

@test("GET /api/v1/links/<code>/extended (owner)")
def _():
    r = api.get(f"/api/v1/links/{owned_code}/extended", headers=auth_headers)
    assert r.status_code == 200
    data = r.get_json()
    assert data["clicks"] == 3
    # The derived fields are not asserted here, and deliberately. On a link
    # made seconds ago every one of them is the answer arithmetic gives
    # whatever the endpoint computes: age_days is 0, so clicks_per_day
    # divides by the max(age, 1) fallback and equals clicks; 3 clicks is
    # under any threshold and today is inside any window. Section 21 asks
    # the same endpoint about a link old enough and busy enough for the
    # four to differ.

@test("GET /api/v1/links/<code> (a stranger's account)")
def _():
    # Signed in, and not the owner. This is the case that separates "may
    # anyone see this" from "is anyone logged in": the anonymous check in
    # section 6 reads a guest link whose owner and last access are None in
    # the row, so it passes even for a service that withholds nothing. This
    # link has an owner, three clicks and a last access, and a stranger is
    # told none of the three.
    r = stranger.get(f"/api/v1/links/{owned_code}")
    assert r.status_code == 200
    data = r.get_json()
    assert data["original_url"] == OWNED_URL
    assert data["clicks"] is None
    assert data["owner_id"] is None
    assert data["last_accessed"] is None

@test("GET /api/v1/links/<code>/extended (a stranger's account)")
def _():
    # 403, not 401: this caller is logged in, and logging in again is not
    # what they are missing. The anonymous check in section 7 only ever
    # reaches the 401 branch, so the refusal below could be deleted from
    # the application without a single check here going red.
    r = stranger.get(f"/api/v1/links/{owned_code}/extended")
    assert r.status_code == 403
    assert r.get_json()["error"] == "FORBIDDEN"

@test("GET /api/v1/links/mine (authenticated)")
def _():
    r = api.get("/api/v1/links/mine", headers=auth_headers)
    assert r.status_code == 200
    # These two and nothing else. Membership would pass for an endpoint
    # that handed back everybody's links along with this account's.
    codes = {link["short_code"] for link in r.get_json()}
    assert codes == {owned_code, browser_code}

@test("GET /api/v1/links/mine (unauthenticated)")
def _():
    r = guest.get("/api/v1/links/mine")
    assert r.status_code == 401


# ─── 12. Stats ─────────────────────────────────────────────────────────
print("\n=== STATS ===")

@test("GET /api/v1/stats (anonymous)")
def _():
    # Asked first, and by nobody: the seeded 'guest' role carries
    # stats:view_basic, so this endpoint has no authenticated path to speak
    # of. Its OpenAPI entry used to declare a 401 that could not happen;
    # the owner decided on 2026-08-09 that the totals stay public, and the
    # entry was brought to the code rather than the other way round.
    #
    # The totals live here rather than on the authenticated check below
    # because this is the read that computes them. The next one is served
    # from the cache this one filled, and would report these numbers
    # whatever its own path counted.
    r = guest.get("/api/v1/stats")
    assert r.status_code == 200
    data = r.get_json()
    # Five guest links, two of this user's, and the four clicks spent on
    # them so far. A floor would pass on a counter that had stopped.
    assert data["total_urls"] == 7
    assert data["total_clicks"] == 4

@test("GET /api/v1/stats (authenticated)")
def _():
    r = api.get("/api/v1/stats", headers=auth_headers)
    assert r.status_code == 200
    # The breakdown carries other people's original URLs and needs
    # stats:view_full, which neither of these callers holds. It is redacted
    # per caller, after the cache, so unlike the totals it is this
    # request's own answer.
    assert r.get_json()["popular_links"] == []

@test("GET /api/v1/stats (invalidated by a new link)")
def _():
    # The totals are cached. Creating a link has to drop that entry, or the
    # service reports yesterday's count until the TTL runs out -- and the
    # two reads above, taken back to back with nothing between them, cannot
    # tell a fresh answer from a stale one.
    assert guest.post(
        "/api/v1/shorten", json={"url": "https://invalidates-stats.example"}
    ).status_code == 201
    r = api.get("/api/v1/stats", headers=auth_headers)
    assert r.status_code == 200
    assert r.get_json()["total_urls"] == 8

@test("GET /api/v1/stats/mine (authenticated)")
def _():
    r = api.get("/api/v1/stats/mine", headers=auth_headers)
    assert r.status_code == 200
    assert r.get_json()["total_clicks"] == 3


# ─── 13. Delete link ───────────────────────────────────────────────────
print("\n=== DELETE LINK ===")

@test("DELETE /api/v1/links/<code> (unauthenticated)")
def _():
    r = guest.delete(f"/api/v1/links/{short_code}")
    # 401 and nothing else. The old assertion accepted 200 as well, with a
    # comment calling it a design choice -- so it would have stayed green
    # if anonymous deletion of anyone's link ever came back.
    assert r.status_code == 401

@test("DELETE /api/v1/links/<code> (nonexistent)")
def _():
    r = api.delete("/api/v1/links/nonexist999", headers=auth_headers)
    assert r.status_code == 404

@test("DELETE /api/v1/links/<code> (guest, with its deletion token)")
def _():
    r = guest.delete(f"/api/v1/links/{short_code}",
                     headers={"X-Deletion-Token": deletion_token})
    assert r.status_code == 200
    assert guest.get(f"/api/v1/links/{short_code}").status_code == 404

@test("DELETE /api/v1/links/<code> (guest, with another link's token)")
def _():
    # A token names the row it was issued for, not a code. Holding one for
    # a link you made is not a licence over the next link in the batch.
    first, second = batch_items[0], batch_items[1]
    r = guest.delete(f"/api/v1/links/{second['short_code']}",
                     headers={"X-Deletion-Token": first["deletion_token"]})
    assert r.status_code == 401
    assert guest.get(f"/api/v1/links/{second['short_code']}").status_code == 200


# ─── 14. Admin endpoints ───────────────────────────────────────────────
print("\n=== ADMIN ENDPOINTS ===")

@test("GET /api/v1/admin/health (unauthenticated)")
def _():
    r = guest.get("/api/v1/admin/health")
    assert r.status_code == 401

@test("GET /api/v1/admin/users (unauthenticated)")
def _():
    r = guest.get("/api/v1/admin/users")
    assert r.status_code == 401

@test("GET /api/v1/admin/roles (unauthenticated)")
def _():
    r = guest.get("/api/v1/admin/roles")
    assert r.status_code == 401

@test("GET /api/v1/admin/users (authenticated, not an admin)")
def _():
    # 403, not 401: logging in is not what this caller is missing, and the
    # two statuses are how a client tells "log in" from "that will not help".
    r = api.get("/api/v1/admin/users", headers=auth_headers)
    assert r.status_code == 403


# ─── 14b. Admin endpoints, from behind the door ────────────────────────
print("\n=== ADMIN ENDPOINTS (AS AN ADMIN) ===")

admin_headers = None
subject_id = None

@test("An administrator, made the way an operator makes the first one")
def _():
    global admin_headers
    r = admin.post("/api/v1/auth/register", json={
        "email": "admin@example.com", "password": "Test1234!"
    })
    assert r.status_code == 201, r.get_json()
    promote_to_admin("admin@example.com")

    # A fresh login, because the token issued at registration was issued to
    # an account that was not an administrator yet.
    r = admin.post("/api/v1/auth/login", json={
        "email": "admin@example.com", "password": "Test1234!"
    })
    assert r.status_code == 200
    admin_headers = {"Authorization": f"Bearer {r.get_json()['access_token']}"}

@test("GET /api/v1/admin/health (as an admin)")
def _():
    r = admin.get("/api/v1/admin/health", headers=admin_headers)
    assert r.status_code == 200
    assert r.get_json()["database"] is True

@test("GET /api/v1/admin/users (as an admin)")
def _():
    r = admin.get("/api/v1/admin/users", headers=admin_headers)
    assert r.status_code == 200
    emails = [u["email"] for u in r.get_json()]
    assert "admin@example.com" in emails
    assert "test@example.com" in emails

@test("POST /api/v1/admin/users (as an admin)")
def _():
    global subject_id
    r = admin.post("/api/v1/admin/users", headers=admin_headers, json={
        "email": "made-by-admin@example.com",
        "password": "Test1234!",
        "roles": ["user"],
    })
    assert r.status_code == 201, r.get_json()
    subject_id = r.get_json()["id"]
    assert r.get_json()["roles"] == ["user"]

@test("GET /api/v1/admin/users/<id> (as an admin)")
def _():
    r = admin.get(f"/api/v1/admin/users/{subject_id}", headers=admin_headers)
    assert r.status_code == 200
    assert r.get_json()["email"] == "made-by-admin@example.com"

@test("GET /api/v1/admin/users/<id> (no such account)")
def _():
    missing = "00000000-0000-0000-0000-000000000000"
    r = admin.get(f"/api/v1/admin/users/{missing}", headers=admin_headers)
    assert r.status_code == 404
    body = r.get_json()
    # The envelope, as every other refusal in this API answers in.
    assert body["error"] == "USER_NOT_FOUND"
    assert body["message"]

@test("PUT /api/v1/admin/users/<id>/roles (as an admin)")
def _():
    r = admin.put(
        f"/api/v1/admin/users/{subject_id}/roles",
        headers=admin_headers,
        json={"roles": ["user", "analyst"]},
    )
    assert r.status_code == 200
    assert sorted(r.get_json()["roles"]) == ["analyst", "user"]

@test("POST /api/v1/admin/users/<id>/deactivate (as an admin)")
def _():
    r = admin.post(
        f"/api/v1/admin/users/{subject_id}/deactivate", headers=admin_headers
    )
    assert r.status_code == 200
    assert r.get_json()["is_active"] is False

@test("A deactivated account cannot log in")
def _():
    # What the deactivation is for, rather than the field it wrote.
    r = new_client("127.0.0.6").post("/api/v1/auth/login", json={
        "email": "made-by-admin@example.com", "password": "Test1234!"
    })
    assert r.status_code == 401

@test("POST /api/v1/admin/users/<id>/activate (as an admin)")
def _():
    r = admin.post(
        f"/api/v1/admin/users/{subject_id}/activate", headers=admin_headers
    )
    assert r.status_code == 200
    assert r.get_json()["is_active"] is True

@test("GET /api/v1/admin/users/<id>/stats (as an admin)")
def _():
    r = admin.get(
        f"/api/v1/admin/users/{subject_id}/stats", headers=admin_headers
    )
    assert r.status_code == 200
    assert r.get_json()["total_links"] == 0

@test("GET /api/v1/admin/roles (as an admin)")
def _():
    r = admin.get("/api/v1/admin/roles", headers=admin_headers)
    assert r.status_code == 200
    names = [role["name"] for role in r.get_json()]
    assert {"admin", "user", "guest"} <= set(names)

@test("POST /api/v1/admin/roles (as an admin)")
def _():
    r = admin.post("/api/v1/admin/roles", headers=admin_headers, json={
        "name": "smoke-editor",
        "description": "Made by the live run",
        "permissions": ["link:create", "link:view_own"],
    })
    assert r.status_code == 201, r.get_json()
    assert r.get_json()["name"] == "smoke-editor"

@test("GET /api/v1/admin/roles/<name> (as an admin)")
def _():
    r = admin.get("/api/v1/admin/roles/smoke-editor", headers=admin_headers)
    assert r.status_code == 200
    granted = sorted(p["name"] for p in r.get_json()["permissions"])
    assert granted == ["link:create", "link:view_own"]

@test("PUT /api/v1/admin/roles/<name>/permissions (as an admin)")
def _():
    r = admin.put(
        "/api/v1/admin/roles/smoke-editor/permissions",
        headers=admin_headers,
        json={"permissions": ["link:create"]},
    )
    assert r.status_code == 200
    assert [p["name"] for p in r.get_json()["permissions"]] == ["link:create"]

@test("DELETE /api/v1/admin/roles/<name> (as an admin)")
def _():
    r = admin.delete(
        "/api/v1/admin/roles/smoke-editor", headers=admin_headers
    )
    assert r.status_code == 200
    assert admin.get(
        "/api/v1/admin/roles/smoke-editor", headers=admin_headers
    ).status_code == 404

@test("DELETE /api/v1/admin/roles/<name> (a system role is refused)")
def _():
    r = admin.delete("/api/v1/admin/roles/admin", headers=admin_headers)
    assert r.status_code == 400
    assert r.get_json()["error"] == "ROLE_DELETION_FAILED"
    # And it is still there.
    assert admin.get(
        "/api/v1/admin/roles/admin", headers=admin_headers
    ).status_code == 200

@test("GET /api/v1/stats (an admin sees the breakdown)")
def _():
    # `stats:view_full` -- the permission that fills popular_links. Every
    # other caller in this file gets it redacted, so a redaction applied to
    # everyone would have looked the same as one applied correctly.
    r = admin.get("/api/v1/stats", headers=admin_headers)
    assert r.status_code == 200
    popular = r.get_json()["popular_links"]
    assert popular, "an admin saw no breakdown at all"
    assert "original_url" in popular[0]

@test("DELETE /api/v1/admin/users/<id> (as an admin)")
def _():
    r = admin.delete(
        f"/api/v1/admin/users/{subject_id}", headers=admin_headers
    )
    assert r.status_code == 200
    assert admin.get(
        f"/api/v1/admin/users/{subject_id}", headers=admin_headers
    ).status_code == 404

@test("DELETE /api/v1/admin/users/<id> (the last administrator is refused)")
def _():
    # The check that keeps a service from being locked out of itself.
    everyone = admin.get("/api/v1/admin/users", headers=admin_headers).get_json()
    admin_id = next(
        u["id"] for u in everyone if u["email"] == "admin@example.com"
    )
    r = admin.delete(f"/api/v1/admin/users/{admin_id}", headers=admin_headers)
    # The exact refusal, not "some 4xx": a check that accepts several
    # answers accepts a broken one, and 401 here would mean the token
    # stopped working rather than the rule holding.
    assert r.status_code == 403, r.get_json()
    assert r.get_json()["error"] == "FORBIDDEN"
    assert admin.get(
        f"/api/v1/admin/users/{admin_id}", headers=admin_headers
    ).status_code == 200


# ─── 15. Web UI routes ─────────────────────────────────────────────────
print("\n=== WEB UI ROUTES ===")

@test("GET / (homepage)")
def _():
    r = guest.get("/")
    assert r.status_code == 200

@test("GET /login")
def _():
    r = guest.get("/login")
    assert r.status_code == 200

@test("GET /register")
def _():
    r = guest.get("/register")
    assert r.status_code == 200

@test("GET /api/docs")
def _():
    r = guest.get("/api/docs")
    assert r.status_code == 200

@test("GET /api/openapi.json")
def _():
    r = guest.get("/api/openapi.json")
    assert r.status_code == 200
    document = r.get_json()
    # The document is checked against the route map by its own test; what
    # matters here is that the route serves it at all.
    assert document["openapi"].startswith("3.")
    assert "/api/v1/shorten" in document["paths"]


DASHBOARD_PAGES = (
    ("/dashboard/", 200),
    ("/dashboard/links", 200),
    ("/dashboard/stats", 200),
    ("/dashboard/create-link", 200),
    ("/dashboard/service/stats", 200),
    ("/dashboard/service/health", 403),
    ("/dashboard/users", 403),
    ("/dashboard/users/new", 403),
    ("/dashboard/users/<user_id>/edit", 403),
    ("/dashboard/users/<user_id>/stats", 403),
    ("/dashboard/roles", 403),
    ("/dashboard/roles/new", 403),
    ("/dashboard/roles/user/edit", 403),
)
"""Every /dashboard rule the application registers, with the answer each
owes a signed-in caller holding the plain 'user' role.

Listed in full rather than sampled: the eight that used to be here were an
incomplete transcription, and the five left out were the parameterised ones
-- exactly the rules a new page is most likely to be added beside.

The second column is what makes these thirteen checks thirteen checks.
``@login_required`` is the outer decorator, so asking as an anonymous
caller measures one thing over and over -- that nobody is logged in -- and
every ``@require_permission`` behind it could be deleted with this file
still green. Five of these pages are the plain role's to open and eight are
not, and that difference is the only evidence those decorators are there.
"""

for _page, _signed_in in DASHBOARD_PAGES:
    @test(f"GET {_page}")
    def _(page=_page, expected=_signed_in):
        path = page.replace("<user_id>", stranger_id)
        # Nobody home: a page answers that with a trip to the login form,
        # not with the 401 an API endpoint would give.
        r = guest.get(path, follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["Location"] == "/login"
        # Somebody home, holding the plain role.
        r = stranger.get(path, follow_redirects=False)
        assert r.status_code == expected


# ─── 16. Error handling ────────────────────────────────────────────────
print("\n=== ERROR HANDLING ===")

@test("404 on unknown API route returns JSON")
def _():
    r = guest.get("/api/v1/nonexistent")
    assert r.status_code == 404
    assert r.get_json()["error"] == "NOT_FOUND"

@test("405 on wrong method returns JSON")
def _():
    r = guest.post("/api/v1/stats")
    assert r.status_code == 405
    assert r.get_json()["error"] == "METHOD_NOT_ALLOWED"


# ─── 17. Rate limiting ─────────────────────────────────────────────────
print("\n=== RATE LIMITING ===")

@test("Rate limit headers present")
def _():
    # A fresh address, so the numbers below are the endpoint's contract
    # rather than a running total of everything this file happened to do
    # first. Tied to `guest`, one added request anywhere above turned this
    # check red for a reason that had nothing to do with it.
    counted = new_client("10.3.0.1")
    r = counted.post("/api/v1/shorten",
                     json={"url": "https://ratelimit-test.com"})
    assert r.status_code == 201
    # The endpoint's own limit, not the default of 100: the headers are
    # what a client paces itself by, and the wrong number is worse than none.
    assert r.headers["X-RateLimit-Limit"] == "30"
    assert r.headers["X-RateLimit-Remaining"] == "29"


# ─── 18. Expired link logic ────────────────────────────────────────────
print("\n=== EXPIRED LINK LOGIC ===")

@test("Link with TTL in past returns 410 on redirect")
def _():
    from datetime import timedelta, timezone
    expired_code = "EXPTEST"
    with app.app_context():
        with db.session() as db_session:
            from sqlalchemy import text
            db_session.execute(text(
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
            db_session.commit()
    r = guest.get(f"/{expired_code}", follow_redirects=False)
    assert r.status_code == 410, f"Expected 410, got {r.status_code}"


# ─── 19. Auth: Logout ──────────────────────────────────────────────────
print("\n=== AUTH: LOGOUT ===")

@test("POST /api/v1/auth/logout (no CSRF token)")
def _():
    r = session_client.post("/api/v1/auth/logout")
    assert r.status_code == 403
    assert r.get_json()["error"] == "CSRF_TOKEN_INVALID"

@test("POST /api/v1/auth/logout")
def _():
    r = session_client.post("/api/v1/auth/logout",
                            headers=csrf(session_client))
    assert r.status_code == 200
    # The session is over, so the cookies that stood for it are gone and
    # the token that guarded them goes with them.
    assert session_client.get_cookie("access_token") is None
    assert session_client.get_cookie("refresh_token") is None
    assert session_client.get_cookie(CSRF_COOKIE_NAME) is None

@test("POST /api/v1/auth/logout (the session is revoked, not just forgotten)")
def _():
    # Emptying the caller's own cookie jar is not logging out: a copied
    # token would go on working. The bearer token minted at the same login
    # is held by another client entirely, and it has to stop working too.
    #
    # 401 is also what a header carrying nothing gets, so the token is
    # checked to be a token first: without this line the check would pass
    # unchanged if the login in section 3 had failed and left it unset.
    assert access_token
    r = api.get("/api/v1/links/mine", headers=auth_headers)
    assert r.status_code == 401


# ─── 20. Validation edge cases ─────────────────────────────────────────
print("\n=== VALIDATION EDGE CASES ===")

@test("POST /api/v1/shorten (URL too long)")
def _():
    r = guest.post("/api/v1/shorten",
                   json={"url": "https://example.com/" + "a" * 2050})
    assert r.status_code == 400
    # Each of these three would answer 400 for either of the other two
    # reasons, and for a fourth nobody meant. The message is the check.
    assert r.get_json()["message"] == "URL too long (max 2048 characters)"

@test("POST /api/v1/shorten (control characters)")
def _():
    r = guest.post("/api/v1/shorten", json={"url": "https://example.com/\x00"})
    assert r.status_code == 400
    assert r.get_json()["message"] == "URL contains control characters"

@test("POST /api/v1/shorten (invalid port)")
def _():
    r = guest.post("/api/v1/shorten", json={"url": "https://example.com:99999"})
    assert r.status_code == 400
    assert r.get_json()["message"] == "Invalid port number"

@test("POST /api/v1/shorten (body that is not an object)")
def _():
    # The request schemas are handed the body as keyword arguments, and
    # ** on anything but a mapping raises before Pydantic is reached. Each
    # of these four answered 500, unauthenticated, until the shape of the
    # body was guarded; nothing here had asked since.
    for body in ("[1, 2]", '"text"', "5", "true"):
        r = guest.post("/api/v1/shorten", data=body,
                       content_type="application/json")
        assert r.status_code == 400, body
        assert r.get_json()["message"] == "Request body must be a JSON object", body


# ─── 21. Derived metrics on a link old enough to have any ──────────────
print("\n=== DERIVED METRICS ===")

@test("GET /api/v1/links/<code>/extended (an aged, busy link)")
def _():
    # Planted rather than created, because the four fields this endpoint
    # exists to compute all collapse on a link made moments ago, and no
    # request can make the clock move. Ten days old with 150 clicks:
    # age_days stops being 0, so clicks_per_day stops being a copy of
    # clicks; 150 is over POPULAR_THRESHOLD and ten days is outside
    # RECENT_DAYS, so is_popular and is_recent each stop being the one
    # answer they could give.
    #
    # Asked after the totals in section 12 for the obvious reason: this row
    # and its 150 clicks would move every one of them.
    from datetime import timedelta, timezone
    aged_code = "AGEDLNK"
    with app.app_context():
        with db.session() as db_session:
            from sqlalchemy import text
            db_session.execute(text(
                "INSERT INTO urls (id, url_hash, short_code, original_url, "
                "created_at, clicks, last_accessed, owner_id, expires_at) "
                "VALUES (:id, :hash, :code, :url, :created, :clicks, "
                ":accessed, :owner, NULL)"
            ), {
                "id": "test-aged-id",
                "hash": "b" * 64,
                "code": aged_code,
                "url": "https://aged.example",
                "created": datetime.now(timezone.utc) - timedelta(days=10),
                "clicks": 150,
                "accessed": datetime.now(timezone.utc) - timedelta(days=2),
                "owner": stranger_id,
            })
            db_session.commit()
    r = new_client("10.3.0.5").get(
        f"/api/v1/links/{aged_code}/extended",
        headers={"Authorization": f"Bearer {stranger_token}"},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["clicks"] == 150
    assert data["age_days"] == 10
    assert data["clicks_per_day"] == 15.0
    assert data["is_popular"] is True
    assert data["is_recent"] is False
    assert data["last_access_days_ago"] == 2


# ─── 22. Ceilings on what a caller may ask for ─────────────────────────
print("\n=== CEILINGS ===")

@test("POST /api/v1/shorten (a guest's TTL is capped at the default)")
def _():
    # Asking for a month gets a week. The check in section 5 asks for an
    # hour, which is under the cap, so min() is never the operative term
    # there and the ceiling could be removed without it noticing.
    r = new_client("10.3.0.2").post("/api/v1/shorten", json={
        "url": "https://long-ttl-guest.example", "ttl_seconds": 30 * 24 * 3600
    })
    assert r.status_code == 201
    assert lifetime(r.get_json()) == 7 * 24 * 3600

@test("POST /api/v1/shorten (an account's TTL is not)")
def _():
    # The cap is the guest allowance, not a global maximum: the same
    # request from an account gets the month it asked for. Without this
    # half, capping everyone would look correct.
    r = new_client("10.3.0.3").post("/api/v1/shorten", json={
        "url": "https://long-ttl-user.example", "ttl_seconds": 30 * 24 * 3600
    }, headers={"Authorization": f"Bearer {stranger_token}"})
    assert r.status_code == 201
    assert lifetime(r.get_json()) == 30 * 24 * 3600

@test("POST /api/v1/shorten (TTL beyond the schema's maximum)")
def _():
    r = new_client("10.3.0.4").post("/api/v1/shorten", json={
        "url": "https://absurd-ttl.example", "ttl_seconds": 10 ** 9
    })
    assert r.status_code == 400
    assert r.get_json()["message"] == "ttl_seconds must not exceed 315360000"


# ─── 23. The guest quota ───────────────────────────────────────────────
print("\n=== GUEST QUOTA ===")

@test("The eleventh guest link from one address is refused")
def _():
    # GUEST_LINK_LIMIT is ten a day per address, and it gets an address of
    # its own: `guest` is at six of ten by the end of section 12 -- three
    # single links plus the three the batch charges to the same quota --
    # so filling a quota there would take the file's own links with it.
    # Asked last because ten more rows would move every total above.
    crowded = new_client("10.3.0.9")
    for i in range(10):
        r = crowded.post("/api/v1/shorten",
                         json={"url": f"https://quota-{i}.example"})
        assert r.status_code == 201, f"link {i + 1} was refused"
    r = crowded.post("/api/v1/shorten", json={"url": "https://quota-10.example"})
    assert r.status_code == 429
    assert r.get_json()["error"] == "GUEST_LINK_LIMIT"


# ─── Summary ────────────────────────────────────────────────────────────
success = result.summary()

# The same guard the suite has in CI, for the same reason: "all passed" is
# a statement about the checks that ran, and says nothing about the ones
# that stopped running. Emptying DASHBOARD_PAGES removed thirteen checks
# and printed a green run and exit 0. A check whose body is only comments
# does the same. Equality, not a floor -- this number is small enough to
# keep honest, and both directions are worth knowing about.
EXPECTED_CHECKS = 110
counted = result.passed + result.failed
if counted != EXPECTED_CHECKS:
    print(f"\nExpected {EXPECTED_CHECKS} checks, ran {counted}.")
    success = False

# And the same guard on the surface rather than on the count. `/static` is
# Flask's own rule, and this run drives the API rather than the pages that
# load assets -- `tests/live/browser_test.py` is what exercises those, in a
# real browser. Nothing else may go unreached without being named here.
NOT_REACHED_ON_PURPOSE = {"/static/<path:filename>"}
all_rules = {str(rule) for rule in app.url_map.iter_rules()}
unreached = sorted(all_rules - touched_rules - NOT_REACHED_ON_PURPOSE)
print(f"\nRoute rules reached: {len(touched_rules)}/{len(all_rules)}")
if unreached:
    print("Never reached by this run:")
    for rule in unreached:
        print(f"  - {rule}")
    success = False

sys.exit(0 if success else 1)
