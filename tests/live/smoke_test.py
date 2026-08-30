"""
Live smoke test over the public surface of the running application.
Run with: uv run python tests/live/smoke_test.py

It covers what an anonymous caller, a programmatic client, a browser
session and an administrator can reach: every route rule the application
registers except `/static`, which is Flask's own. The number is not
maintained by hand -- the run records which rule answered each request and
fails if one was never reached.

The administrator is made the way an operator makes the first one, by
writing the role onto an account (`grant_role`): there is no endpoint
for it and should not be, since the first administrator cannot be appointed
by an administrator.

Ten clients, because one cannot stand for ten callers. A Flask test
client keeps a cookie jar, so the moment any request on it logs in, every
later request on that client is a cookie-authenticated one -- and the CSRF
layer refuses unsafe cookie-authenticated requests that carry no token,
before the request reaches any logic. A single shared client therefore
turned every later POST and DELETE into 403 and, worse, turned each
"anonymous" check into a check on a signed-in caller.

Six of them are roles a caller can be; the other four are second devices,
and they exist because two sections replace an account's password.

  - ``guest``    never authenticates. It is what an anonymous caller is.
  - ``api``      authenticates with ``Authorization: Bearer`` and holds no
                 cookies, which is what a programmatic client is. CSRF does
                 not apply to it, by design.
  - ``session``  logs in and keeps the cookies, which is what a browser is.
                 Every unsafe request on it goes through ``csrf()``.
  - ``admin``    an account with the admin role, written straight into
                 the database the way an operator makes the first one.
  - ``auditor``  an account holding the `auditor` role: the two journal
                 permissions and the health report, and nothing that
                 writes. It exists because the administrator cannot stand
                 in for it -- `admin:all` deliberately does not carry
                 `audit:view`, so the same run needs a caller who has it.
  - ``stranger`` a second account, logged in and entitled to nothing here.
                 Without it the file has only an owner and an anonymous
                 caller, and every per-object authorization check could be
                 deleted from the application with this run still green:
                 "logged in, but not yours" is a third answer, and it is
                 the one those checks exist to give.

  - ``changer`` and ``changer_second`` are two devices of one further
                 account, for the section that changes that account's
                 password. Sharing the account with the sections around it
                 would leave them unable to sign in halfway through the
                 run; sharing one client between the two devices would make
                 "the other device was signed out" a claim about the device
                 that made the change.
  - ``forgetful`` and ``forgetful_second`` are the same pair for the reset
                 section, which replaces a password too -- and reads the
                 link out of a delivered message, so its account also has
                 to be the only one that was mailed anything recently.

Every client answers from an address of its own, and the checks that measure
a quota get a fresh one. The guest quota counts per address throughout; the
rate limiter counts per address only while the caller is anonymous and
switches to the account once one is signed in, so `session_client` and
`api` share a bucket whatever addresses they claim. A shared address makes
each check the neighbour of whatever preceded it: registrations are three
per hour, so a fourth scenario would measure the throttle rather than what
it is named after.
"""

import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from flask import request

from mail_catcher import MailCatcher

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

mail = MailCatcher()
"""This run's mail server. It accepts mail and sends it nowhere."""


class SmokeConfig(TestingConfig):
    """
    The run's profile: testing as it stands, but with mail on and pointed
    here.

    Without it, address confirmation had to be acted out -- the run issued a
    token itself and wrote its digest into the table itself, which checks
    ``/api/v1/auth/verify`` against a string the service did not issue.
    Nothing then checked that registration issues a token, that the template
    builds the link, or that the message goes out at all.
    """

    MAIL_ENABLED = True
    MAIL_HOST = "127.0.0.1"
    MAIL_PORT = mail.port
    MAIL_USE_TLS = False
    MAIL_USE_SSL = False
    MAIL_FROM = "no-reply@link-shortener.test"


app = create_app(config=SmokeConfig())

touched_rules = set()


@app.after_request
def _record_the_rule_that_answered(response):
    """
    Note which route rule answered, so coverage is counted not claimed.

    A number stated in the docstring would be maintained by hand and could
    not notice a check being deleted, renamed, or quietly pointed somewhere
    else.

    The path *and* the method, because six of these paths carry two of
    them -- `GET` and `DELETE` on `/api/v1/links/<short_code>`, `GET` and
    `POST` on `/api/v1/auth/verify`, and four more under `/admin/`.
    Counting paths alone, those two answers were one entry: a `DELETE`
    added to a path some `GET` already reached raised no denominator and
    could go unchecked with the run still printing full coverage.

    `HEAD` is recorded as the `GET` it mirrors. Flask serves it off the
    `GET` rule and never registers one of its own, so leaving it as sent
    would add a pair no denominator below has.

    Args:
        response: The response about to be returned.

    Returns:
        The response, untouched.
    """
    if request.url_rule is not None:
        method = "GET" if request.method == "HEAD" else request.method
        touched_rules.add((str(request.url_rule), method))
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


def grant_role(email: str, role_name: str) -> None:
    """
    Put a seeded role on an account, the way an operator would.

    There is no endpoint for the first of these and there should not be:
    the first administrator cannot be made by an administrator. The row is
    written directly, which is what `flask db` does and what the deployment
    notes tell an operator to do.

    Used for ``auditor`` as well, and for a reason worth stating: an
    administrator *can* grant it through the API, and that is exactly the
    path the permission split leaves open on purpose -- it leaves a record.
    Granting it here keeps this run measuring the journals rather than
    measuring the grant.

    Args:
        email: Address of the account.
        role_name: Name of a seeded role.
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
                text("SELECT id FROM roles WHERE name = :name"),
                {"name": role_name},
            ).fetchone()
            assert user is not None, f"no account for {email}"
            assert role is not None, f"the {role_name} role was never seeded"
            session.execute(
                text(
                    "INSERT OR IGNORE INTO user_roles (user_id, role_id) "
                    "VALUES (:uid, :rid)"
                ),
                {"uid": user[0], "rid": role[0]},
            )
            session.commit()

def mailed_link(email: str) -> str:
    """
    Take the last link with a token in it out of what was mailed.

    Serves both kinds of message, and the name says so: the confirmation
    and the password reset are the same problem read the same way, and the
    reader matches on the token rather than on a path. Which one comes
    back is decided by which message was delivered last, which is why the
    reset checks register their own account.

    Nothing here mints a token and nothing here spells the path. The use
    case issues the token, the template builds the link, the mailer
    submits the message over SMTP, and this reads back exactly what was
    delivered -- so a token that stopped being issued, a link built on a
    path nothing answers, and a message that never left all fail here.

    Rebuilding the path from a known constant would undo that: measured --
    with the path written out here, a ``VERIFY_PATH`` changed to
    ``/auth/verify`` still gave 114/114.

    Only the path is handed back, and the origin is deliberately not
    checked here. A test client can be given a path and nothing else, so
    the only comparison available would be against ``BASE_URL`` -- the
    same value the link was built from, which makes the assertion agree
    with itself: with that check in place a ``BASE_URL`` of
    ``http://attacker.example/`` still gives 114/114.

    The host the link is built on is checked where the comparison can be
    independent, against a ``Host`` header the caller chose:
    ``tests/integration/web/controllers/test_confirmation_link_is_built_from_configuration.py``.
    ``browser_test.py`` covers it from the other side, by opening the whole
    URL in a browser.

    Args:
        email: Address the message was sent to.

    Returns:
        Path with query string, as the link carries them.
    """
    target = mail.confirmation_target(email)
    assert target is not None, f"no message carrying a link reached {email}"
    return target


def token_from(link: str) -> str:
    """
    Take the token out of a mailed link, of either kind.

    Args:
        link: Path with query string, as the message carries it.

    Returns:
        The token, unescaped.
    """
    query = parse_qs(urlparse(link).query)
    token = query.get("token", [""])[0]
    assert token, f"no token in {link!r}"
    return token


def confirm_email(email: str) -> None:
    """
    Confirm an address the way its owner does.

    The mailed link opens a page; the page's button sends the token. So
    this reads the token out of the delivered link and posts it, which is
    the request that button makes. Following the link alone confirms
    nothing on purpose -- see the checks around ``/verify``.

    Every account this run signs in with has to get past the confirmation
    first: registration leaves it unconfirmed and login refuses it until
    the address is proven.

    Args:
        email: Address of the account to confirm.
    """
    link = mailed_link(email)

    # The link is followed, not just parsed. Reading the token out and
    # posting it to a path written here would confirm the address whatever
    # the message actually said: measured -- with only the post, a
    # ``VERIFY_PATH`` pointing at a route nothing answers left this run at
    # 114 of 115, because every account still got confirmed. Following it
    # first puts the link itself back in the path of every check that
    # needs an account.
    landing = new_client("10.0.0.98").get(link)
    assert landing.status_code == 200, (
        f"the mailed link answered {landing.status_code}: {link}"
    )

    token = token_from(link)
    response = new_client("10.0.0.99").post(
        "/api/v1/auth/verify", json={"token": token}
    )
    assert response.status_code == 200, response.get_json()


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
    assert r.status_code == 202
    # No account comes back. The same answer is given for an address that
    # is already registered, and one that named the account would only be
    # answerable for one of the two.
    assert set(r.get_json()) == {"message"}

@test("A fresh registration cannot sign in yet")
def _():
    # The account exists and the password is right; what it lacks is a
    # confirmed address. Named apart from a wrong password on purpose --
    # this is the one refusal the holder can act on, and only somebody who
    # already knows the password ever sees it.
    r = new_client("10.0.0.30").post("/api/v1/auth/login", json={
        "email": "test@example.com", "password": "Test1234!"
    })
    assert r.status_code == 401, r.get_json()
    assert r.get_json()["error"] == "EMAIL_NOT_VERIFIED", r.get_json()

@test("GET /api/v1/auth/verify (a link that was never issued)")
def _():
    r = new_client("10.0.0.31").get("/api/v1/auth/verify?token=never-issued")
    assert r.status_code == 400, r.get_json()

@test("GET /verify (the mailed link lands on a page, and spends nothing)")
def _():
    # The link points at a page now, not at the endpoint. Loading it must
    # not confirm anything: mail scanners follow links, and a load that
    # spent the token would leave its owner told that their confirmation
    # is invalid.
    link = mailed_link("test@example.com")
    r = new_client("10.0.0.32").get(link)
    assert r.status_code == 200, r.status_code
    assert r.headers["Content-Type"].startswith("text/html"), r.headers["Content-Type"]
    assert b"verify-btn" in r.data, "the page carries no button to press"

@test("POST /api/v1/auth/verify (the real token)")
def _():
    # What the button on that page sends.
    token = token_from(mailed_link("test@example.com"))
    r = new_client("10.0.0.37").post("/api/v1/auth/verify", json={"token": token})
    assert r.status_code == 200, r.get_json()

    # And once only: the same token again is refused, in the same words as
    # a token that never existed.
    again = new_client("10.0.0.33").post(
        "/api/v1/auth/verify", json={"token": token}
    )
    unknown = new_client("10.0.0.36").get("/api/v1/auth/verify?token=no-such")
    assert again.status_code == unknown.status_code == 400
    assert again.get_json()["message"] == unknown.get_json()["message"]

@test("POST /api/v1/auth/resend-verification (an address nobody holds)")
def _():
    # Answers the same as for a registered one. A route that mails on
    # request and answers honestly is a route that says who is registered.
    unknown = new_client("10.0.0.34").post(
        "/api/v1/auth/resend-verification",
        json={"email": "nobody-here@example.com"},
    )
    known = new_client("10.0.0.35").post(
        "/api/v1/auth/resend-verification",
        json={"email": "test@example.com"},
    )
    assert unknown.status_code == 202, unknown.get_json()
    assert known.status_code == unknown.status_code
    assert known.get_json()["message"] == unknown.get_json()["message"]

@test("POST /api/v1/auth/register (duplicate)")
def _():
    # Compared against a fresh registration rather than against a literal:
    # what matters is that the two are indistinguishable, and a pair of
    # hard-coded 202s would still pass if only one of them changed.
    duplicate = new_client("10.0.0.2").post("/api/v1/auth/register", json={
        "email": "test@example.com", "password": "Test1234!"
    })
    fresh = new_client("10.0.0.42").post("/api/v1/auth/register", json={
        "email": "never-used@example.com", "password": "Test1234!"
    })
    assert duplicate.status_code == 202, duplicate.get_json()
    assert duplicate.status_code == fresh.status_code
    assert duplicate.get_json() == fresh.get_json()

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
        assert r.status_code == 202, f"attempt {i} was refused"
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
    assert r.status_code == 202
    confirm_email("stranger@example.com")
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


# ─── 4b. Auth: Password change ────────────────────────────────────────
print("\n=== AUTH: PASSWORD CHANGE ===")

# Its own account, registered here and used nowhere else. The checks below
# replace its password, and an account shared with a later section would
# be a section that stops being able to sign in halfway through the run.
CHANGER = "changer@example.com"
CHANGER_OLD = "Test1234!"
CHANGER_NEW = "Changed5678!"

changer = new_client("10.0.0.60")
changer_second = new_client("10.0.0.61")
changer_second_token = None

@test("An account of its own to change the password of")
def _():
    global changer_second_token
    r = changer.post("/api/v1/auth/register", json={
        "email": CHANGER, "password": CHANGER_OLD
    })
    assert r.status_code == 202, r.get_json()
    confirm_email(CHANGER)
    r = changer.post("/api/v1/auth/login", json={
        "email": CHANGER, "password": CHANGER_OLD
    })
    assert r.status_code == 200, r.get_json()
    # A second sign-in from its own client: this is the device the change
    # is supposed to throw out, and it has to exist before the change.
    r = changer_second.post("/api/v1/auth/login", json={
        "email": CHANGER, "password": CHANGER_OLD
    })
    assert r.status_code == 200, r.get_json()
    changer_second_token = r.get_json()["access_token"]

@test("POST /api/v1/auth/change-password (nobody signed in)")
def _():
    r = new_client("10.0.0.62").post("/api/v1/auth/change-password", json={
        "current_password": CHANGER_OLD, "new_password": CHANGER_NEW
    })
    assert r.status_code == 401, r.get_json()

@test("POST /api/v1/auth/change-password (the wrong current password)")
def _():
    r = changer.post(
        "/api/v1/auth/change-password",
        json={"current_password": "not-it", "new_password": CHANGER_NEW},
        headers=csrf(changer),
    )
    assert r.status_code == 400, r.get_json()
    # Named rather than generalised: the caller is already inside the
    # account, so there is nothing left for a vague answer to protect.
    assert r.get_json()["details"][0]["field"] == "current_password", r.get_json()

@test("POST /api/v1/auth/change-password (the password it already has)")
def _():
    r = changer.post(
        "/api/v1/auth/change-password",
        json={"current_password": CHANGER_OLD, "new_password": CHANGER_OLD},
        headers=csrf(changer),
    )
    assert r.status_code == 400, r.get_json()

@test("POST /api/v1/auth/change-password (a password the policy refuses)")
def _():
    r = changer.post(
        "/api/v1/auth/change-password",
        json={"current_password": CHANGER_OLD, "new_password": "123"},
        headers=csrf(changer),
    )
    assert r.status_code == 400, r.get_json()

@test("POST /api/v1/auth/change-password (the change takes)")
def _():
    r = changer.post(
        "/api/v1/auth/change-password",
        json={"current_password": CHANGER_OLD, "new_password": CHANGER_NEW},
        headers=csrf(changer),
    )
    assert r.status_code == 200, r.get_json()
    assert set(r.get_json()) == {"access_token", "refresh_token"}

    # The password afterwards is the new one and not the old one, asked
    # from a client that was never signed in as anybody.
    refused = new_client("10.0.0.63").post("/api/v1/auth/login", json={
        "email": CHANGER, "password": CHANGER_OLD
    })
    assert refused.status_code == 401, refused.get_json()
    accepted = new_client("10.0.0.64").post("/api/v1/auth/login", json={
        "email": CHANGER, "password": CHANGER_NEW
    })
    assert accepted.status_code == 200, accepted.get_json()

@test("A password change signs out the other devices, not this one")
def _():
    # The other device's token is still a validly signed claim; what
    # stopped it is that the session it names has been revoked.
    r = changer_second.get(
        "/api/v1/links/mine",
        headers={"Authorization": f"Bearer {changer_second_token}"},
    )
    assert r.status_code == 401, r.status_code
    # And it cannot refresh its way back in.
    r = changer_second.post(
        "/api/v1/auth/refresh", headers=csrf(changer_second)
    )
    assert r.status_code == 401, r.status_code
    # The client that made the change kept working, on the cookies the
    # answer replaced -- with no token echoed here at all.
    r = changer.get("/api/v1/links/mine")
    assert r.status_code == 200, r.status_code


# ─── 4c. Auth: Password reset by mail ─────────────────────────────────
print("\n=== AUTH: PASSWORD RESET ===")

# Its own account again, and for the same reason: these checks replace its
# password, so an account shared with a later section would be one that
# stops being able to sign in halfway through the run.
FORGETFUL = "forgetful@example.com"
FORGETFUL_OLD = "Test1234!"
FORGETFUL_NEW = "Remembered9!"

forgetful = new_client("10.0.0.70")
forgetful_second = new_client("10.0.0.71")
forgetful_second_token = None
reset_link = None

@test("An account of its own to reset the password of")
def _():
    global forgetful_second_token
    r = forgetful.post("/api/v1/auth/register", json={
        "email": FORGETFUL, "password": FORGETFUL_OLD
    })
    assert r.status_code == 202, r.get_json()
    confirm_email(FORGETFUL)
    # A device that is signed in when the reset happens, so that "every
    # session goes" is a claim about something that existed.
    r = forgetful_second.post("/api/v1/auth/login", json={
        "email": FORGETFUL, "password": FORGETFUL_OLD
    })
    assert r.status_code == 200, r.get_json()
    forgetful_second_token = r.get_json()["access_token"]

@test("GET /forgot-password (the page that asks for a link)")
def _():
    r = new_client("10.0.0.72").get("/forgot-password")
    assert r.status_code == 200, r.status_code
    assert b"forgot-form" in r.data, "the page carries no form to submit"

@test("POST /api/v1/auth/forgot-password (an address nobody holds)")
def _():
    # Answers the same as for a registered one, word for word. A route
    # that mails on request and answers honestly says who is registered.
    unknown = new_client("10.0.0.73").post(
        "/api/v1/auth/forgot-password",
        json={"email": "nobody-here@example.com"},
    )
    known = new_client("10.0.0.74").post(
        "/api/v1/auth/forgot-password", json={"email": FORGETFUL}
    )
    assert unknown.status_code == 202, unknown.get_json()
    assert known.status_code == unknown.status_code
    assert known.get_json()["message"] == unknown.get_json()["message"]

@test("GET /reset-password (the mailed link lands on a page, and spends nothing)")
def _():
    global reset_link
    # Read back out of the message that was delivered, path and all. A
    # path written here instead would pass a `RESET_PATH` pointing
    # anywhere -- which is exactly how the confirmation link was measured.
    reset_link = mailed_link(FORGETFUL)
    r = new_client("10.0.0.75").get(reset_link)
    assert r.status_code == 200, r.status_code
    assert r.headers["Content-Type"].startswith("text/html"), r.headers["Content-Type"]
    assert b"reset-form" in r.data, "the page carries no form to submit"

@test("POST /api/v1/auth/reset-password (a token nobody issued)")
def _():
    r = new_client("10.0.0.76").post(
        "/api/v1/auth/reset-password",
        json={"token": "never-issued", "new_password": FORGETFUL_NEW},
    )
    assert r.status_code == 400, r.get_json()

@test("POST /api/v1/auth/reset-password (the real token)")
def _():
    token = token_from(reset_link)
    r = new_client("10.0.0.77").post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": FORGETFUL_NEW},
    )
    assert r.status_code == 200, r.get_json()
    # Nobody was signed in by it: the account was just opened by a link
    # out of a mailbox, and the first thing it should ask for is the
    # password that was chosen.
    assert "access_token" not in r.get_json()

    # And once only. The same token again is refused in the same words as
    # one that never existed -- "already used" would say an account exists
    # and somebody reset it.
    again = new_client("10.0.0.78").post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "Third1234!"},
    )
    unknown = new_client("10.0.0.79").post(
        "/api/v1/auth/reset-password",
        json={"token": "no-such-token", "new_password": "Third1234!"},
    )
    assert again.status_code == unknown.status_code == 400
    assert again.get_json()["message"] == unknown.get_json()["message"]

@test("A reset replaces the password and signs out every device")
def _():
    refused = new_client("10.0.0.80").post("/api/v1/auth/login", json={
        "email": FORGETFUL, "password": FORGETFUL_OLD
    })
    assert refused.status_code == 401, refused.get_json()
    accepted = new_client("10.0.0.81").post("/api/v1/auth/login", json={
        "email": FORGETFUL, "password": FORGETFUL_NEW
    })
    assert accepted.status_code == 200, accepted.get_json()

    # The device that was signed in before the reset. Its access token is
    # still a validly signed claim; the session it names is gone.
    r = forgetful_second.get(
        "/api/v1/links/mine",
        headers={"Authorization": f"Bearer {forgetful_second_token}"},
    )
    assert r.status_code == 401, r.status_code


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

@test("POST /api/v1/batch/shorten (a refused item names its code)")
def _():
    # The fourth of the five requests a minute this address is allowed
    # here, and the last one this section spends.
    #
    # A per-item refusal reads the way the error envelope does: `error` is
    # the code, `message` is the sentence. It used to hold the sentence
    # under the envelope's name for the code, so the only way to tell a
    # malformed URL from a spent quota was to match on text -- text that
    # changes with the reader's language.
    r = guest.post("/api/v1/batch/shorten", json={"urls": ["not-a-url"]})
    assert r.status_code == 200
    item = r.get_json()["results"][0]
    assert item["success"] is False
    assert item["error"] == "VALIDATION_ERROR"
    assert item["message"] and item["message"] != item["error"]


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
    # of, and its OpenAPI entry declares no 401: the totals are public by
    # decision, and the entry follows the code.
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

@test("GET /api/v1/stats/visits (the redirects of this run are in it)")
def _():
    # The counter and the chart are written in one transaction, so they
    # have to agree: this run has redirected three times by now, and both
    # `/stats/mine` above and this endpoint must say so.
    r = api.get("/api/v1/stats/visits?period=24h")
    assert r.status_code == 200
    body = r.get_json()
    assert body["total"] >= 3, body
    assert len(body["buckets"]) == 24
    assert sum(bucket["total"] for bucket in body["buckets"]) == body["total"]
    # A short code is somebody's link: naming one needs stats:view_full,
    # which the guest role does not carry.
    assert body["top_links"] == []

@test("GET /api/v1/stats/visits/daily (one entry per day, ending today)")
def _():
    r = api.get("/api/v1/stats/visits/daily?days=7")
    assert r.status_code == 200
    days = r.get_json()["days"]
    assert len(days) == 7, days
    # Today, not tomorrow: the span runs to midnight tonight.
    today = datetime.now(timezone.utc).date().isoformat()
    assert days[-1]["at"].startswith(today), days[-1]

@test("GET /api/v1/stats/visits (a period nobody offers)")
def _():
    r = api.get("/api/v1/stats/visits?period=forever")
    assert r.status_code == 400
    assert r.get_json()["error"] == "VALIDATION_ERROR"


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
    assert r.status_code == 202, r.get_json()
    grant_role("admin@example.com", "admin")
    confirm_email("admin@example.com")

    # Signed in here rather than at registration: registration issues no
    # tokens at all, and the role this account needs is granted above.
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

# The two endpoints below act on an account that is stuck: registered,
# never confirmed, and therefore refused at the login form. The account
# made through the admin API cannot stand in for it -- that one is
# confirmed at creation, on the grounds that an administrator typed the
# address -- and against a confirmed account both endpoints are no-ops
# that still answer as if they had worked.
STUCK = "never-confirmed@example.com"
stuck_id = None

@test("An account that registered and never confirmed reads as unverified")
def _():
    global stuck_id
    r = new_client("127.0.0.7").post("/api/v1/auth/register", json={
        "email": STUCK, "password": "Test1234!"
    })
    assert r.status_code == 202, r.get_json()

    listing = admin.get("/api/v1/admin/users", headers=admin_headers)
    assert listing.status_code == 200
    rows = [u for u in listing.get_json() if u["email"] == STUCK]
    assert len(rows) == 1, listing.get_json()
    # Both states, which is the distinction the column was missing: an
    # account can be enabled and still unable to sign in.
    assert rows[0]["is_active"] is True
    assert rows[0]["email_verified"] is False
    stuck_id = rows[0]["id"]

@test("POST /api/v1/admin/users/<id>/resend-verification (as an admin)")
def _():
    # Counted before and after rather than looked for once: the catcher
    # keeps everything this run delivered, so "a message is there" would
    # also be true of the one registration itself sent.
    before = len(mail.messages_to(STUCK))
    r = admin.post(
        f"/api/v1/admin/users/{stuck_id}/resend-verification",
        headers=admin_headers,
    )
    assert r.status_code == 202, r.get_json()
    assert STUCK in r.get_json()["message"]
    assert len(mail.messages_to(STUCK)) == before + 1, (
        "the endpoint answered but no message left the service"
    )

@test("POST /api/v1/admin/users/<id>/verify-email (as an admin)")
def _():
    r = admin.post(
        f"/api/v1/admin/users/{stuck_id}/verify-email", headers=admin_headers
    )
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["email_verified"] is True

    # Pressing it again is not an error: two operators reaching for the
    # same account both want the state it already has.
    again = admin.post(
        f"/api/v1/admin/users/{stuck_id}/verify-email", headers=admin_headers
    )
    assert again.status_code == 200, again.get_json()

@test("An account confirmed by an administrator can log in")
def _():
    # What the button is for, rather than the field it wrote: until it ran,
    # this same request answered 401 EMAIL_NOT_VERIFIED -- the refusal
    # checked further up, on an account nobody had confirmed either.
    r = new_client("127.0.0.7").post("/api/v1/auth/login", json={
        "email": STUCK, "password": "Test1234!"
    })
    assert r.status_code == 200, r.get_json()

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
    assert r.get_json()["error"] == "ROLE_IS_SYSTEM"
    # And it is still there.
    assert admin.get(
        "/api/v1/admin/roles/admin", headers=admin_headers
    ).status_code == 200

@test("GET /api/v1/stats/visits (an admin sees which links they were)")
def _():
    r = admin.get("/api/v1/stats/visits?period=24h", headers=admin_headers)
    assert r.status_code == 200
    assert r.get_json()["top_links"], "the breakdown is withheld from an admin too"

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


# ─── 14c. The journals, and who reads which ────────────────────────────
print("\n=== JOURNALS ===")

# A sixth client, and the only one whose whole point is what it may *not*
# do. The administrator above cannot stand in for it: `admin:all` does not
# carry `audit:view`, so an admin asking for the audit journal is refused
# -- which is the arrangement this section exists to prove, and it needs
# both sides of it in one run.
auditor = new_client("127.0.0.9")
auditor_headers = None


@test("An auditor, holding the reading permissions and nothing that writes")
def _():
    global auditor_headers
    r = auditor.post("/api/v1/auth/register", json={
        "email": "auditor@example.com", "password": "Test1234!"
    })
    assert r.status_code == 202, r.get_json()
    grant_role("auditor@example.com", "auditor")
    confirm_email("auditor@example.com")

    r = auditor.post("/api/v1/auth/login", json={
        "email": "auditor@example.com", "password": "Test1234!"
    })
    assert r.status_code == 200
    auditor_headers = {"Authorization": f"Bearer {r.get_json()['access_token']}"}

@test("GET /api/v1/journals/application (as an auditor)")
def _():
    r = auditor.get("/api/v1/journals/application", headers=auditor_headers)
    assert r.status_code == 200, r.get_json()
    page = r.get_json()
    # The shape, not the contents: what is in the file depends on what this
    # deployment has done, and a run that asserted a particular line would
    # be asserting its own history.
    assert page["journal"] == "application"
    assert isinstance(page["lines"], list)
    assert isinstance(page["reached_start"], bool)
    # Every line says which file it came from, and on a read that did not
    # ask for the archives that can only be the live journal.
    for line in page["lines"]:
        assert line["source"] == "application.log", line["source"]
        assert set(line) == {"raw", "fields", "parsed", "source"}

@test("GET /api/v1/journals/audit (as an auditor)")
def _():
    r = auditor.get("/api/v1/journals/audit", headers=auditor_headers)
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["journal"] == "audit"

@test("GET /api/v1/journals/error (as an auditor)")
def _():
    r = auditor.get("/api/v1/journals/error", headers=auditor_headers)
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["journal"] == "error"

@test("GET /api/v1/journals/application (as an admin)")
def _():
    # The operational journals are ordinary administrative work, and
    # withholding them would be ceremony rather than separation of duties.
    r = admin.get("/api/v1/journals/application", headers=admin_headers)
    assert r.status_code == 200, r.get_json()

@test("GET /api/v1/journals/audit (an admin is refused)")
def _():
    # The whole arrangement, in one check. An administrator holds every
    # power the audit journal records, so `admin:all` deliberately does not
    # carry `audit:view` -- they can still take the `auditor` role, and
    # taking it is itself an event.
    r = admin.get("/api/v1/journals/audit", headers=admin_headers)
    assert r.status_code == 403, r.get_json()
    assert r.get_json()["error"] == "FORBIDDEN"

@test("GET /api/v1/journals/application (authenticated, entitled to neither)")
def _():
    r = api.get("/api/v1/journals/application", headers=auth_headers)
    assert r.status_code == 403

@test("GET /api/v1/journals/audit (unauthenticated)")
def _():
    # 401 rather than 403: nobody is signed in, and the two statuses are
    # how a client tells "log in" from "logging in will not help".
    r = guest.get("/api/v1/journals/audit")
    assert r.status_code == 401

@test("GET /api/v1/journals/<name> (a name no journal has)")
def _():
    # The enum is what keeps a string in the address from becoming a path,
    # and the refusal is about the name rather than about a permission:
    # answering 403 here would tell an anonymous caller that a journal by
    # that name exists.
    r = auditor.get("/api/v1/journals/passwd", headers=auditor_headers)
    assert r.status_code == 404
    assert r.get_json()["error"] == "JOURNAL_NOT_FOUND"

@test("GET /api/v1/journals/application?limit= (outside the range)")
def _():
    # Refused rather than trimmed: a caller who asked for ten thousand
    # lines and silently got two thousand has been told the journal holds
    # two thousand lines.
    for asked in ("0", "-1", "20000", "all"):
        r = auditor.get(
            f"/api/v1/journals/application?limit={asked}",
            headers=auditor_headers,
        )
        assert r.status_code == 400, f"limit={asked} answered {r.status_code}"
        assert r.get_json()["error"] == "VALIDATION_ERROR"

@test("GET /api/v1/journals/application?archives=true")
def _():
    # Rotation may have left archives beside the live journal or not, so
    # what is checked is that asking for them is answered and that
    # everything handed back is still a file belonging to this journal --
    # `application.log`, `application.log.1`, `application.log.2.gz`.
    r = auditor.get(
        "/api/v1/journals/application?archives=true&limit=50",
        headers=auditor_headers,
    )
    assert r.status_code == 200, r.get_json()
    for name in r.get_json()["files_read"]:
        assert name.startswith("application.log"), name

@test("GET /api/v1/journals/counters (as an auditor)")
def _():
    # The figures the charts are drawn from. They are the audit journal
    # counted, so they open to the same permission -- which is why this
    # runs on the auditor and the next one on the administrator.
    r = auditor.get("/api/v1/journals/counters", headers=auditor_headers)
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["period"] == "7d", body
    assert isinstance(body["totals"], dict), body
    # This run has signed in several times by now, so the one event that
    # cannot be absent is a successful sign-in.
    assert body["totals"].get("LOGIN_SUCCEEDED", 0) > 0, body

@test("GET /api/v1/journals/counters (an administrator is refused)")
def _():
    # The limit of `admin:all`, measured through this endpoint: these
    # numbers summarise the record kept about administrators, and a count
    # is the same information as a record, aggregated.
    r = api.get("/api/v1/journals/counters", headers=auth_headers)
    assert r.status_code == 403, r.get_json()

@test("GET /api/v1/journals/counters?period= (outside the four on offer)")
def _():
    # Refused rather than trimmed to the nearest: a caller free to name a
    # span is a caller free to name a bucket count.
    r = auditor.get(
        "/api/v1/journals/counters?period=all-of-it", headers=auditor_headers
    )
    assert r.status_code == 400, r.get_json()

@test("GET /api/v1/journals/counters (every span answers with its own width)")
def _():
    widths = {"24h": 24, "7d": 28, "30d": 30, "90d": 90}
    for period, buckets in widths.items():
        r = auditor.get(
            f"/api/v1/journals/counters?period={period}",
            headers=auditor_headers,
        )
        assert r.status_code == 200, r.get_json()
        body = r.get_json()
        assert body["buckets"] == buckets, (period, body["buckets"])
        for name, series in body["series"].items():
            assert len(series) == buckets, (period, name, len(series))

@test("GET /dashboard/service/journals (as an auditor)")
def _():
    # The page itself, which is guarded by `require_any_permission` --
    # either permission opens it, because either has something to show.
    r = auditor.get("/dashboard/service/journals", follow_redirects=False)
    assert r.status_code == 200


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
    # The page about one link. `200` for the plain role and any code:
    # the page is a shell, and the figures on it are narrowed to the
    # caller's own links by the endpoint it fetches -- a code belonging
    # to somebody else answers with zeroes rather than with a refusal.
    ("/dashboard/links/<short_code>/stats", 200),
    ("/dashboard/create-link", 200),
    # Open to every signed-in account and guarded by no permission: what
    # is on it belongs to whoever is reading it.
    ("/dashboard/security", 200),
    ("/dashboard/service/stats", 200),
    ("/dashboard/service/health", 403),
    # Neither `audit:view` nor `logs:view` is in the plain role, so the
    # page is closed to it -- and it is open to the auditor, which is
    # checked in section 14c. Both halves are needed: a page guarded by
    # `require_any_permission("audit:view", "logs:view")` and a page
    # guarded by nothing at all give the same answer to one of them.
    ("/dashboard/service/journals", 403),
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

Listed in full rather than sampled: a partial transcription leaves out the
parameterised rules, which are exactly the ones a new page is most likely
to be added beside.

The second column is what makes these fifteen checks fifteen checks.
``@login_required`` is the outer decorator, so asking as an anonymous
caller measures one thing over and over -- that nobody is logged in -- and
every ``@require_permission`` behind it could be deleted with this file
still green. Seven of these pages are the plain role's to open and eight
are not, and that difference is the only evidence those decorators are
there.
"""

for _page, _signed_in in DASHBOARD_PAGES:
    @test(f"GET {_page}")
    def _(page=_page, expected=_signed_in):
        path = page.replace("<user_id>", stranger_id).replace(
            "<short_code>", "smokeCode1"
        )
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
# that stopped running. Emptying DASHBOARD_PAGES removed fourteen checks
# and printed a green run and exit 0. A check whose body is only comments
# does the same. Equality, not a floor -- this number is small enough to
# keep honest, and both directions are worth knowing about.
EXPECTED_CHECKS = 157
counted = result.passed + result.failed
if counted != EXPECTED_CHECKS:
    print(f"\nExpected {EXPECTED_CHECKS} checks, ran {counted}.")
    success = False

# And the same guard on the surface rather than on the count. `/static` is
# Flask's own rule, and this run drives the API rather than the pages that
# load assets -- `tests/live/browser_test.py` is what exercises those, in a
# real browser. Nothing else may go unreached without being named here.
NOT_REACHED_ON_PURPOSE = {("/static/<path:filename>", "GET")}

# One entry per (path, method), which is what a caller can actually ask
# for. Counted over paths alone this was 49, and six of them carried two
# methods each: `GET` and `DELETE` on a link, `GET` and `POST` on the
# confirmation endpoint, and four under `/admin/`. A method added to a
# path already reached moved nothing, so it could ship unchecked with the
# run still printing full coverage.
#
# `HEAD` and `OPTIONS` are dropped rather than counted: Flask adds both to
# every rule on its own, nobody wrote them, and requiring a check for each
# would ask this run to prove Werkzeug works.
all_rules = {
    (str(rule), method)
    for rule in app.url_map.iter_rules()
    for method in (rule.methods or set())
    if method not in {"HEAD", "OPTIONS"}
}
unreached = sorted(all_rules - touched_rules - NOT_REACHED_ON_PURPOSE)
print(f"\nRoute rules reached: {len(touched_rules)}/{len(all_rules)}")
if unreached:
    print("Never reached by this run:")
    for path, method in unreached:
        print(f"  - {method} {path}")
    success = False

mail.stop()

sys.exit(0 if success else 1)
