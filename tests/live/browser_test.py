"""
The page scripts, executed by a browser.

``web/static/js/pages/*.js`` was reached by nothing. The one test about
scripts asserted that a filename appears in the markup, and ``tests/e2e``
drives the Flask test client, which has no browser in it -- so the eight
files that turn an API answer into something a person reads are, as far as
any other run can tell, empty. Reversing ``data.message || data.error`` in
all eight -- putting the machine-readable code back in front of the
sentence on every form -- leaves the suite and
the live run green.

Run it by hand, as ``smoke_test.py`` is run:

    uv run python tests/live/browser_test.py

It is not collected by pytest (``python_files = "test_*.py"`` does not match
the name) and is not part of CI: a browser is a new kind of run, and the
decision to add one to CI is not this file's to make.

The server is a real one on a real port, because that is the whole point --
a test client cannot execute a script. The database is a file in a
temporary directory rather than ``:memory:``: the server answers on worker
threads, and an in-memory SQLite database is not shared between the
connections they take from the pool.
"""

import re
import socket
import sys
import tempfile
import threading
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from mail_catcher import MailCatcher

from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.web.app_factory import create_app


PASSWORD = "Str0ng!Passw0rd"


class Result:
    """Counts what ran, so a run that checks nothing cannot report success."""

    def __init__(self):
        self.passed = 0
        self.failed = 0

    def ok(self, name):
        """Record a passing check."""
        self.passed += 1
        print(f"  PASS  {name}")

    def fail(self, name, why):
        """Record a failing check."""
        self.failed += 1
        print(f"  FAIL  {name}: {why}")


result = Result()


def check(name):
    """
    Run one check, catching whatever it raises.

    Args:
        name: What the check is called in the output.

    Returns:
        Decorator that runs the function immediately.
    """
    def wrap(function):
        try:
            function()
            result.ok(name)
        except AssertionError as error:
            result.fail(name, str(error) or "assertion failed")
        except Exception as error:  # noqa: BLE001 - reported, not swallowed
            result.fail(name, f"{type(error).__name__}: {error}")
            traceback.print_exc()
        return function
    return wrap


def free_port() -> int:
    """
    Find a port nothing is listening on.

    Returns:
        A port number the server can bind.
    """
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def build_app(database_path: Path, base_url: str, mail_port: int, log_dir: Path):
    """
    Build the application against a file database.

    Args:
        database_path: Where the SQLite file goes.
        base_url: Where this run serves from. It has to reach the
            configuration: the CSRF layer refuses an unsafe request whose
            ``Origin`` is not in ``CORS_ORIGINS``, and a browser sends the
            real one -- a port picked at random here. Without this the
            forms answer 403 and the run reads as eight broken scripts.
            It is also the base the confirmation link is built on, so the
            browser can follow the link straight out of the message.
        mail_port: Port the catcher of this run listens on.
        log_dir: Where this run writes its journals. Its own directory,
            because the journal page reads what the service wrote: pointed
            at the default, the checks on it would read whatever the
            developer's tree happens to hold -- green on a machine with an
            old `datas/logs` and red on a fresh clone, and never a
            statement about this run.

    Returns:
        The Flask application, tables created and roles seeded.
    """
    class BrowserConfig(TestingConfig):
        DATABASE_URL = f"sqlite:///{database_path}"
        CORS_ORIGINS = [base_url]
        # So the short URL a page shows points at this run rather than at
        # the shipped default, which makes the assertion about it real.
        BASE_URL = base_url
        # The forms are what is under test; a limit reached mid-run would
        # look like a broken script.
        DEFAULT_RATE_LIMIT = 10_000
        RATE_LIMITS = {}
        # Mail goes to the catcher of this run. Before it, confirmation
        # was a direct `UPDATE users SET email_verified = 1`, and the one
        # step a visitor actually performs -- opening the link out of the
        # message -- was performed by nobody.
        MAIL_ENABLED = True
        MAIL_HOST = "127.0.0.1"
        MAIL_PORT = mail_port
        MAIL_USE_TLS = False
        MAIL_USE_SSL = False
        MAIL_FROM = "no-reply@link-shortener.test"
        # Journals on, and written to this run's own directory. The page
        # under test displays them, so a run with logging off would be
        # checking that an empty table renders.
        LOGGING_ENABLED = True
        AUDIT_ENABLED = True
        LOG_TO_FILE = True
        LOG_TO_CONSOLE = False
        LOG_DIR = str(log_dir)

    app = create_app(config=BrowserConfig())
    with app.app_context():
        from link_shortener.infrastructure.database.seed import seed_base_roles

        db = app.container.get_db_manager()
        db.create_tables()
        with db.session() as session:
            seed_base_roles(session)
    return app


def is_a_server_answer(text: str) -> bool:
    """
    Say whether a console error is just the service refusing something.

    A ``fetch`` that comes back 401 or 404 is printed to the console by the
    browser itself, and several of the checks here ask for exactly that.
    What this run is looking for is a script that threw.

    Args:
        text: The console message.

    Returns:
        ``True`` when the message is the browser reporting an HTTP status.
    """
    return "Failed to load resource" in text


def is_a_code(text: str) -> bool:
    """
    Say whether a message is a machine-readable code rather than a sentence.

    ``VALIDATION_ERROR`` is what the pages showed before their scripts put
    ``data.message`` first, and it is one word in capitals with
    underscores. A sentence has spaces and lower-case letters in it.

    Args:
        text: What the page put in front of the visitor.

    Returns:
        ``True`` when it reads as a code.
    """
    first = text.split()[0] if text.split() else text
    return first.isupper() and " " not in text.strip()


def confirm_email(page, mail: MailCatcher, email: str) -> None:
    """
    Confirm an address the way its owner does: by opening the mailed link
    and pressing the button on the page it lands on.

    Registration leaves the account unconfirmed and the login form refuses
    it until the address is proven. Before, this step was a direct
    ``UPDATE users SET email_verified = 1``, which proved nothing about
    the token registration issues, the link the template builds or the
    page that link lands on -- and one of those broke once without a
    single check going red.

    The click is the confirmation now. The link used to point straight at
    the API, which answered JSON to a person's browser and spent the token
    on whatever fetched it first.

    Args:
        page: An open browser page, used to follow the link.
        mail: The catcher this run's messages were delivered to.
        email: Address of the account to confirm.
    """
    link = mail.confirmation_link(email)
    assert link is not None, f"no confirmation message was delivered to {email}"

    response = page.goto(link)
    assert response is not None and response.status == 200, (
        f"the mailed link answered {response and response.status}: {link}"
    )
    page.click("#verify-btn")
    page.wait_for_function(
        "document.getElementById('verify-done').textContent.trim() !== ''"
        " || document.getElementById('verify-error').textContent.trim() !== ''",
        timeout=5000,
    )
    assert page.inner_text("#verify-error").strip() == "", (
        page.inner_text("#verify-error")
    )


def grant_role(app, email: str, role_name: str) -> None:
    """
    Put a seeded role on an account, the way an operator would.

    There is no endpoint for the first administrator and there should not
    be: the first one cannot be appointed by an administrator. The row is
    written directly, which is what ``smoke_test.py`` does for the same
    reason.

    Used for ``auditor`` as well: the journal page needs a caller holding
    a permission ``admin:all`` does not carry.

    Args:
        app: The running application.
        email: Address of the account.
        role_name: Name of a seeded role.
    """
    from sqlalchemy import text

    with app.app_context():
        with app.container.get_db_manager().session() as session:
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


def record_visits(app, email: str) -> int:
    """
    Give an account a link with a week of traffic behind it.

    Written straight into the tables, the way ``grant_role`` writes a
    role, and for a related reason: the charts are about a *span*, and
    every redirect this run could serve would be stamped "now" -- a week of
    them would draw one column and prove nothing about the other
    twenty-seven.

    The shape is deliberate rather than uniform: robots are a minority,
    device classes are uneven, and the browsers run past three families so
    that the ring has a tail to fold into "Others".

    Args:
        app: The running application.
        email: Owner of the link the visits belong to.

    Returns:
        How many visit rows were written.
    """
    import hashlib
    import random
    import uuid
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import text

    rnd = random.Random(11)
    now = datetime.now(timezone.utc)
    devices = ["desktop", "desktop", "desktop", "mobile", "mobile", "tablet", "unknown"]
    browsers = ["chrome", "chrome", "safari", "firefox", "edge", "opera"]
    url = "https://example.com/charted"

    with app.app_context():
        with app.container.get_db_manager().session() as session:
            owner = session.execute(
                text("SELECT id FROM users WHERE email = :email"), {"email": email}
            ).fetchone()
            assert owner is not None, f"no account for {email}"

            # A second link owned by somebody else, with traffic of its
            # own. Without it, "a stranger's link reports zero" is a check
            # that would also pass against a link nobody ever opened --
            # and that is the reading it must not have.
            stranger_id = str(uuid.uuid4())
            session.execute(text(
                "INSERT INTO users (id, email, password_hash, is_active, "
                "email_verified, created_at) "
                "VALUES (:id, :email, :hash, 1, 1, :now)"
            ), {"id": stranger_id, "email": "browser-owner@example.test",
                "hash": "not-a-usable-hash", "now": now})

            links = {}
            for code, owner_id in (("charted01", owner[0]),
                                   ("foreign01", stranger_id)):
                link_id = str(uuid.uuid4())
                links[code] = link_id
                session.execute(text(
                    "INSERT INTO urls (id, url_hash, original_url, short_code, "
                    "owner_id, clicks, created_at) "
                    "VALUES (:id, :hash, :url, :code, :owner, :clicks, :made)"
                ), {
                    "id": link_id,
                    "hash": hashlib.sha256(f"{url}/{code}".encode()).hexdigest(),
                    "url": f"{url}/{code}",
                    "code": code,
                    "owner": owner_id,
                    "clicks": 0,
                    "made": now - timedelta(days=30),
                })

            written = 0
            for hours_back in range(24 * 7):
                moment = now - timedelta(hours=hours_back)
                for code, link_id in links.items():
                    for _ in range(rnd.randint(0, 3)):
                        is_bot = rnd.random() < 0.2
                        session.execute(text(
                            "INSERT INTO link_visits (id, link_id, occurred_at, "
                            "visitor_network, device, browser, is_bot) "
                            "VALUES (:id, :link, :at, :net, :device, :browser, :bot)"
                        ), {
                            "id": str(uuid.uuid4()),
                            "link": link_id,
                            "at": moment,
                            "net": "203.0.113.0",
                            "device": rnd.choice(devices),
                            "browser": "bot" if is_bot else rnd.choice(browsers),
                            "bot": is_bot,
                        })
                        written += 1
            session.commit()
    return written


def sign_in(page, base: str) -> None:
    """
    Sign the browser in through the login form.

    Args:
        page: An open page already at ``/login``.
        base: Base URL the server answers on.
    """
    page.fill("#email", "browser-user@example.test")
    page.fill("#password", PASSWORD)
    page.click("#login-form button[type=submit]")
    page.wait_for_url(f"{base}/dashboard/", timeout=5000)


def main() -> int:
    """
    Serve the application and drive it with a browser.

    Returns:
        Process exit code: 0 when every check passed.
    """
    with tempfile.TemporaryDirectory() as workspace:
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        mail = MailCatcher()
        journals = Path(workspace) / "journals"
        journals.mkdir()
        app = build_app(Path(workspace) / "browser.db", base, mail.port, journals)
        server = make_server("127.0.0.1", port, app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(f"Serving on {base}\n")

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    run_checks(browser, base, mail, app)
                finally:
                    browser.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)
            mail.stop()

    print("\n" + "=" * 60)
    print(f"Results: {result.passed}/{result.passed + result.failed} passed, "
          f"{result.failed} failed")
    print("=" * 60)

    # The same guard smoke_test.py carries: a run that stopped checking
    # things prints a green summary otherwise.
    expected = 41
    counted = result.passed + result.failed
    if counted != expected:
        print(f"\nExpected {expected} checks, ran {counted}.")
        return 1

    return 0 if result.failed == 0 else 1


def run_checks(browser, base: str, mail: MailCatcher, app) -> None:
    """
    Drive every page whose script turns an answer into a sentence.

    Args:
        browser: A launched Playwright browser.
        base: Base URL the server answers on.
        mail: Catcher holding the messages this run sent, from which the
            confirmation link is taken.
        app: The running application, for the one thing no endpoint does:
            making the first administrator.
    """
    console_errors = []

    def page_for(path: str, viewport: dict | None = None):
        """
        Open a page and collect its console errors.

        Args:
            path: Where to go, relative to the base address.
            viewport: Size to open at. The default is Playwright's, which
                is a desktop; the sidebar's own toggle is drawn only under
                a media query, so the check on it has to ask for a narrow
                one or it clicks a control that is `display: none`.
        """
        page = browser.new_page(viewport=viewport) if viewport \
            else browser.new_page()
        page.on("console", lambda message: (
            console_errors.append(f"{path}: {message.text}")
            if message.type == "error" and not is_a_server_answer(message.text)
            else None
        ))
        page.goto(f"{base}{path}")
        return page

    @check("the landing page shortens a link and shows the short URL")
    def _():
        page = page_for("/")
        page.fill("#url-single", "https://example.com/from-a-browser")
        page.click("#form-single button[type=submit]")
        page.wait_for_selector("#result .result-url", timeout=5000)
        shown = page.inner_text("#result .result-url").strip()

        assert shown.startswith(base), f"result was {shown!r}"
        assert shown.rstrip("/").rsplit("/", 1)[-1], f"no code in {shown!r}"
        # And the address that was submitted, so a script rendering the
        # wrong field is caught rather than merely a missing one.
        assert "from-a-browser" in page.inner_text("#result")

    @check("a refused shortening shows a sentence, not a code")
    def _():
        page = page_for("/")
        # A shape the browser's own `type="url"` accepts, so the form
        # actually submits and the answer comes from the service: an
        # underscore is legal in a URL and not in a host label.
        page.fill("#url-single", "https://a_b.example/x")
        page.click("#form-single button[type=submit]")
        page.wait_for_selector("#result .alert--error", timeout=5000)
        message = page.inner_text("#result .alert--error").strip()

        assert message, "the error area stayed empty"
        # The defect this file exists for. `data.error` first puts
        # VALIDATION_ERROR on the page in place of the sentence beside it,
        # and a machine-readable code is what that looks like: one word,
        # capitals and underscores.
        assert not is_a_code(message), (
            f"the page shows a machine-readable code: {message!r}"
        )

    @check("registration refuses a weak password in words")
    def _():
        page = page_for("/register")
        page.fill("#email", "browser-weak@example.test")
        # Long enough for the field's own `minlength`, so the refusal
        # comes from the policy rather than from the browser.
        page.fill("#password", "password")
        page.click("#register-form button[type=submit]")
        page.wait_for_function(
            "document.getElementById('reg-error').textContent.trim() !== ''",
            timeout=5000,
        )
        message = page.inner_text("#reg-error").strip()

        assert message, "the error area stayed empty"
        assert not is_a_code(message), (
            f"the page shows a machine-readable code: {message!r}"
        )

    @check("registration tells the visitor to go and read their mail")
    def _():
        # No longer a redirect to /login: the account cannot sign in until
        # the mailed link is opened, and the answer is the same whether or
        # not the address was free -- so the page shows what the API said.
        page = page_for("/register")
        page.fill("#email", "browser-user@example.test")
        page.fill("#password", PASSWORD)
        page.click("#register-form button[type=submit]")
        page.wait_for_function(
            "document.getElementById('reg-sent').textContent.trim() !== ''",
            timeout=5000,
        )
        message = page.inner_text("#reg-sent").strip()

        assert message, "the acknowledgement area stayed empty"
        assert not is_a_code(message), (
            f"the page shows a machine-readable code: {message!r}"
        )
        assert page.is_hidden("#register-form"), (
            "the form is still offering to register the same address again"
        )

    @check("a fresh registration cannot sign in until the address is confirmed")
    def _():
        page = page_for("/login")
        page.fill("#email", "browser-user@example.test")
        page.fill("#password", PASSWORD)
        page.click("#login-form button[type=submit]")
        page.wait_for_function(
            "document.getElementById('login-error').textContent.trim() !== ''",
            timeout=5000,
        )
        message = page.inner_text("#login-error").strip()

        assert message, "the error area stayed empty"
        assert not is_a_code(message), (
            f"the page shows a machine-readable code: {message!r}"
        )

        # From here on the account is usable: the checks below are about
        # signing in and the dashboard, not about confirmation.
        confirm_email(page, mail, "browser-user@example.test")

    @check("signing in with the wrong password says so in words")
    def _():
        page = page_for("/login")
        page.fill("#email", "browser-user@example.test")
        page.fill("#password", "Wr0ng!Passw0rd")
        page.click("#login-form button[type=submit]")
        page.wait_for_function(
            "document.getElementById('login-error').textContent.trim() !== ''",
            timeout=5000,
        )
        message = page.inner_text("#login-error").strip()

        assert message, "the error area stayed empty"
        assert not is_a_code(message), (
            f"the page shows a machine-readable code: {message!r}"
        )

    @check("signing in reaches the dashboard")
    def _():
        sign_in(page_for("/login"), base)

    @check("signing out lands on the front page, and the session is gone")
    def _():
        page = page_for("/login")
        sign_in(page, base)
        page.click("#logout-btn")
        page.wait_for_url(f"{base}/", timeout=5000)

        # Where it landed is half the check. The other half is that the
        # session really ended: a script that navigated without waiting for
        # the answer would look identical here, and would leave the browser
        # holding a live cookie.
        page.goto(f"{base}/dashboard/")
        assert "/login" in page.url, (
            f"the dashboard still opened after signing out: {page.url}"
        )

    @check("the collapsed sidebar stays collapsed on the next page")
    def _():
        # The point of the control is that it is not asked for twice. The
        # state rides on a cookie the server reads, so the check is the
        # class the *next* page was rendered with rather than the class the
        # script left behind on this one.
        page = page_for("/login")
        sign_in(page, base)
        assert page.is_visible("#dash-collapse"), "no control to collapse with"
        page.click("#dash-collapse")
        page.wait_for_selector("#dash.dash--rail", timeout=5000)

        page.goto(f"{base}/dashboard/links")
        assert "dash--rail" in page.get_attribute("#dash", "class"), (
            "the sidebar came back open on the next page"
        )
        # Measured rather than asked about: a clipped label still reports
        # itself visible, and the class alone says nothing about whether a
        # stylesheet acted on it.
        width = page.evaluate(
            "document.getElementById('dash-side').getBoundingClientRect().width"
        )
        assert width < 80, f"the sidebar is still {width}px wide"

        # The words leave the screen; the name a screen reader announces
        # stays, which is why the labels are clipped and not removed.
        assert "My Links" in page.inner_text("#dash-side"), (
            "the entry lost its accessible name along with its label"
        )

        # And back, so the check leaves the browser as it found it -- the
        # next check signs in with the same profile.
        page.click("#dash-collapse")
        page.goto(f"{base}/dashboard/")
        assert "dash--rail" not in page.get_attribute("#dash", "class"), (
            "expanding it again did not survive the next page"
        )

    @check("the menu button on a narrow screen says whether it is open")
    def _():
        # `aria-expanded` is the only thing this control tells a screen
        # reader about its state -- the sidebar sliding into view is not
        # something that can be heard. It said nothing at all until the
        # attribute was added, so "Menu, button" was the announcement both
        # before the press and after it.
        #
        # Driven at 420px because `.dash-toggle` is `display: none` until
        # the media query, and a click on an invisible control measures
        # nothing. The assertions pair the attribute with the class the
        # stylesheet actually acts on, so an attribute that flips while
        # the menu stays shut is a failure too.
        page = page_for("/login", viewport={"width": 420, "height": 900})
        sign_in(page, base)

        assert page.is_visible("#dash-toggle"), "no menu button at 420px"
        assert page.get_attribute("#dash-toggle", "aria-controls") == "dash-side", (
            "the button does not say which element it opens"
        )
        assert page.get_attribute("#dash-toggle", "aria-expanded") == "false", (
            "the button starts out claiming the menu is open"
        )

        page.click("#dash-toggle")
        page.wait_for_selector("#dash-side.active", timeout=5000)
        assert page.get_attribute("#dash-toggle", "aria-expanded") == "true", (
            "the menu opened and the button still says it is closed"
        )

        # The way back is a press outside: at this width the open sidebar
        # covers the button, so pressing it again is not something a
        # visitor can do.
        page.mouse.click(400, 700)
        page.wait_for_selector("#dash-side:not(.active)", timeout=5000)
        assert page.get_attribute("#dash-toggle", "aria-expanded") == "false", (
            "the menu closed and the button still says it is open"
        )

    @check("the dashboard creates a link through its own form")
    def _():
        page = page_for("/login")
        sign_in(page, base)
        page.goto(f"{base}/dashboard/create-link")
        page.fill("#url", "https://example.com/from-the-dashboard")
        page.click("#create-link-form button[type=submit]")
        page.wait_for_function(
            "document.getElementById('create-result').textContent.trim() !== ''"
            " || document.getElementById('create-error').textContent.trim() !== ''",
            timeout=5000,
        )

        assert page.inner_text("#create-error").strip() == "", (
            page.inner_text("#create-error")
        )
        assert base.split("//")[1] in page.inner_text("#create-result")

    @check("the confirmation link opens a page rather than a JSON body")
    def _():
        # What arrives in a mailbox is opened by a browser. The link used
        # to point at the API, which answers `application/json`: the
        # person who did what the message asked was shown
        # {"message": "Email confirmed..."} and left to find the sign-in
        # page themselves.
        page = page_for("/register")
        page.fill("#email", "browser-verify@example.test")
        page.fill("#password", PASSWORD)
        page.click("#register-form button[type=submit]")
        page.wait_for_function(
            "document.getElementById('reg-sent').textContent.trim() !== ''",
            timeout=5000,
        )

        link = mail.confirmation_link("browser-verify@example.test")
        assert link is not None, "no confirmation message was delivered"
        page.goto(link)

        assert page.is_visible("#verify-btn"), (
            "the mailed link did not land on a page with a button on it"
        )

    @check("opening the confirmation link does not spend the token")
    def _():
        # A scanner that follows links in mail would otherwise confirm the
        # address -- or, worse, spend the token and leave its owner told
        # that their confirmation is invalid. Loading the page twice and
        # only then pressing the button proves the load is inert.
        page = page_for("/login")
        link = mail.confirmation_link("browser-verify@example.test")
        page.goto(link)
        page.goto(link)
        page.click("#verify-btn")
        page.wait_for_function(
            "document.getElementById('verify-done').textContent.trim() !== ''"
            " || document.getElementById('verify-error').textContent.trim() !== ''",
            timeout=5000,
        )

        assert page.inner_text("#verify-error").strip() == "", (
            "the token was already spent by loading the page: "
            + page.inner_text("#verify-error")
        )
        assert page.is_visible("#verify-next"), (
            "the page confirmed the address and offered no way to sign in"
        )

    @check("the sign-in page can ask for another confirmation message")
    def _():
        # The service has always answered this request and no page ever
        # made it: someone whose message never arrived was stuck.
        page = page_for("/login")
        page.fill("#email", "browser-user@example.test")
        page.click("#resend-link")
        page.wait_for_function(
            "document.getElementById('resend-done').textContent.trim() !== ''"
            " || document.getElementById('resend-error').textContent.trim() !== ''",
            timeout=5000,
        )

        assert page.inner_text("#resend-error").strip() == "", (
            page.inner_text("#resend-error")
        )
        message = page.inner_text("#resend-done").strip()
        assert message and not is_a_code(message), message

    @check("an administrator sees the roles each account holds")
    def _():
        # The column read `{{ role.name }}` over a list of names, and
        # Undefined prints as nothing: it was blank for every account in
        # the service, on the page whose job is to say who holds what.
        grant_role(app, "browser-user@example.test", "admin")
        page = page_for("/login")
        sign_in(page, base)
        page.goto(f"{base}/dashboard/users")

        row = page.inner_text("tr[data-user-email='browser-user@example.test']")
        assert "admin" in row, f"the Roles column says nothing: {row!r}"

    @check("an administrator can suspend an account from the users page")
    def _():
        page = page_for("/login")
        sign_in(page, base)
        page.goto(f"{base}/dashboard/users")
        row = "tr[data-user-email='browser-verify@example.test']"
        page.on("dialog", lambda dialog: dialog.accept())
        page.click(f"{row} .js-deactivate")
        page.wait_for_selector(f"{row} .js-activate", timeout=5000)

        assert "Inactive" in page.inner_text(row), page.inner_text(row)

    @check("a page that is refused its data says so instead of loading forever")
    def _():
        # The defect the page scripts all shared: `if (!resp.ok) return;`
        # left the table on "Loading..." for good, so a refusal and a slow
        # network looked identical to the person waiting.
        #
        # The refusal is arranged with `route`, which belongs to the page
        # and outlives a navigation. This check used to assign
        # `window.fetch` and then reload -- and a reload builds a new
        # document, so the assignment went with the old one. The script ran
        # against the live service, the table filled in with this account's
        # own links, "Loading" disappeared because the data arrived, and
        # every assertion below held. Measured: with the silent
        # `if (!resp.ok) return;` put back in `my_links.js`, the check
        # stayed green -- it was passing over the exact defect it names.
        page = page_for("/login")
        sign_in(page, base)
        page.route("**/api/v1/links/mine", lambda route: route.fulfill(
            status=403,
            content_type="application/json",
            # `message` beside `error`, because the sentence is half of
            # what this check is about: the scripts put `data.message`
            # first, and a page that shows `FORBIDDEN` fails the last
            # assertion below.
            body='{"error": "FORBIDDEN", "message": "Not authorized"}',
        ))
        page.goto(f"{base}/dashboard/links")
        page.wait_for_function(
            "document.getElementById('links-tbody').textContent.indexOf('Loading') === -1",
            timeout=5000,
        )
        shown = page.inner_text("#links-tbody").strip()

        assert "Loading" not in shown, "the table is still saying Loading"
        assert shown, "the table went blank instead of saying what happened"
        assert not is_a_code(shown), (
            f"the page shows a machine-readable code: {shown!r}"
        )

    # ------------------------------------------------------------------
    # The charts
    #
    # Nothing but a browser draws them, and no run that reads markup can
    # tell a chart from an empty box: the panel, the legend and the
    # controls are all in the page whether or not a single column was
    # ever painted. What is measured here is the drawing itself -- how
    # many marks, at what coordinates, in which language.
    # ------------------------------------------------------------------

    visits_written = record_visits(app, "browser-user@example.test")

    def open_stats(path="/dashboard/stats", language=None):
        """
        Sign in and open a statistics page with the charts drawn.

        Args:
            path: Which of the two statistics pages to open.
            language: Language cookie to set before loading, or ``None``
                to let the negotiation decide.

        Returns:
            The page, once the first chart has marks on it.
        """
        page = page_for("/login")
        sign_in(page, base)
        if language:
            page.context.add_cookies([{
                "name": "lang", "value": language,
                "domain": "127.0.0.1", "path": "/",
            }])
        page.goto(f"{base}{path}")
        page.wait_for_selector("[data-visit-columns] svg path", timeout=8000)
        return page

    @check("the visits chart draws one column per bucket the service sent")
    def _():
        assert visits_written > 0, "no visits were recorded to chart"
        page = open_stats()
        # The service decides how many buckets a span is cut into, so the
        # count is taken from the answer rather than written here: a chart
        # that quietly drops the last bucket would otherwise pass.
        buckets = page.evaluate(
            "async () => (await (await fetch("
            "'/api/v1/stats/visits?scope=mine&period=7d',"
            " {credentials: 'same-origin'})).json()).buckets.length"
        )
        marks = page.eval_on_selector_all(
            "[data-visit-columns] svg path", "nodes => nodes.length"
        )
        box = page.get_attribute("[data-visit-columns] svg", "viewBox")

        assert box, "the chart has no viewBox -- nothing was drawn"
        assert buckets == 28, f"the service cut 7d into {buckets} buckets"
        # One mark per non-empty bucket, and a stacked one adds a second:
        # between one and two per bucket, never zero and never more.
        assert 0 < marks <= buckets * 2, f"{marks} marks over {buckets} buckets"

    @check("choosing a span redraws the chart against that span")
    def _():
        page = open_stats()
        before = page.eval_on_selector_all(
            "[data-visit-columns] svg path", "nodes => nodes.length"
        )
        page.click("[data-visit-period='24h']")
        # Waiting for the *new* axis, not for an axis: the old one is
        # still on screen while the request is in flight, and a wait for
        # "some text exists" is satisfied by the chart that was already
        # there. Written the loose way first, and it failed against a
        # working page -- the drawing was right and the check was early.
        page.wait_for_function(
            "Array.from(document.querySelectorAll('[data-visit-columns] svg text'))"
            ".some(node => node.textContent.indexOf(':') !== -1)",
            timeout=8000,
        )
        # The axis is the honest witness here: 24 hourly buckets are
        # labelled with clock times, and a chart that ignored the press
        # would still be showing dates.
        labels = page.eval_on_selector_all(
            "[data-visit-columns] svg text",
            "nodes => nodes.map(n => n.textContent)"
        )
        pressed = page.get_attribute("[data-visit-period='24h']", "aria-pressed")

        assert pressed == "true", "the pressed span is not marked as pressed"
        assert before > 0, "there was nothing on the chart to begin with"
        assert any(":" in text for text in labels), (
            f"no clock time on the axis of a 24-hour span: {labels}"
        )

    @check("a breakdown switches between a ring and bars and remembers it")
    def _():
        page = open_stats()
        page.wait_for_selector("[data-visit-share=devices] svg path", timeout=5000)
        page.click("[data-visit-shape=devices]")
        page.wait_for_selector("[data-visit-share=devices] .chart-bars-fill", timeout=5000)

        bars = page.eval_on_selector_all(
            "[data-visit-share=devices] .chart-bars-fill", "nodes => nodes.length"
        )
        assert bars > 0, "the switch left the panel empty"
        # Colour follows the category, not the shape: the first row is the
        # same hue in both, or switching the shape repaints the data.
        first = page.eval_on_selector(
            "[data-visit-share=devices] .chart-bars-fill",
            "node => getComputedStyle(node).backgroundColor"
        )

        # And the browsers panel is untouched, because the choice is per
        # breakdown rather than per page.
        assert page.query_selector("[data-visit-share=browsers] svg path"), (
            "switching devices also switched browsers"
        )

        # The choice survives leaving the page and coming back, which is
        # the whole point of remembering it.
        page.goto(f"{base}/dashboard/service/stats")
        page.wait_for_selector("[data-visit-share=devices] .chart-bars-fill", timeout=8000)
        again = page.eval_on_selector(
            "[data-visit-share=devices] .chart-bars-fill",
            "node => getComputedStyle(node).backgroundColor"
        )

        assert again == first, f"the row changed colour: {first} then {again}"

    @check("hovering a column says what it is made of")
    def _():
        page = open_stats()
        page.hover("[data-visit-columns] .chart-hit >> nth=20")
        page.wait_for_selector("[data-visit-columns] .chart-tip.active", timeout=5000)
        shown = page.inner_text("[data-visit-columns] .chart-tip").strip()

        assert shown, "the tooltip appeared empty"
        # Three rows: the total and the two parts it is made of. A
        # tooltip naming only the total would hide the half of the answer
        # the stack exists to show.
        assert len(shown.splitlines()) >= 4, f"the tooltip says too little: {shown!r}"

    @check("a span with no visits says so instead of drawing an empty box")
    def _():
        page = page_for("/login")
        sign_in(page, base)
        # Through `route`, which belongs to the page and outlives a
        # navigation -- the lesson the refusal check above paid for.
        page.route("**/api/v1/stats/visits?*", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"since": "2026-08-01T00:00:00+00:00",'
                 ' "until": "2026-08-08T00:00:00+00:00",'
                 ' "total": 0, "bots": 0, "buckets": [],'
                 ' "devices": [], "browsers": [], "top_links": []}',
        ))
        page.goto(f"{base}/dashboard/stats")
        page.wait_for_selector("[data-visit-columns] svg text", timeout=8000)
        drawn = page.eval_on_selector_all(
            "[data-visit-columns] svg text", "nodes => nodes.map(n => n.textContent)"
        )
        marks = page.eval_on_selector_all(
            "[data-visit-columns] svg path", "nodes => nodes.length"
        )

        assert marks == 0, "an empty span drew columns"
        # A sentence, not just an axis: the frame alone is the empty box
        # this check exists to forbid.
        assert any(len(text.split()) > 2 for text in drawn), (
            f"nothing on the chart says the span was empty: {drawn}"
        )

    @check("a chart refused its figures says so rather than staying blank")
    def _():
        page = page_for("/login")
        sign_in(page, base)
        page.route("**/api/v1/stats/visits?*", lambda route: route.fulfill(
            status=403,
            content_type="application/json",
            body='{"error": "FORBIDDEN", "message": "Not authorized"}',
        ))
        page.goto(f"{base}/dashboard/stats")
        page.wait_for_selector("[data-visit-error]:not(.hidden)", timeout=8000)
        message = page.inner_text("[data-visit-error]").strip()
        figure = page.get_attribute("[data-visit-columns]", "class") or ""

        assert message, "the error area stayed empty"
        assert not is_a_code(message), (
            f"the page shows a machine-readable code: {message!r}"
        )
        assert "chart-figure--failed" in figure, (
            "the chart does not show that its figures are missing"
        )

    @check("the poll timer does not outlive the page that started it")
    def _():
        # The most expensive mistake available on this page, and one no
        # markup can show: a page script is re-executed on every Turbo
        # navigation, and a `setInterval` it started is not stopped by the
        # body being swapped. Ten navigations would leave ten timers
        # polling for statistics nobody is looking at.
        page = page_for("/login")
        sign_in(page, base)
        polls = []
        page.on("request", lambda request: (
            polls.append(request.url)
            if "/api/v1/stats/visits" in request.url else None
        ))
        page.goto(f"{base}/dashboard/stats")
        page.wait_for_selector("[data-visit-columns] svg", timeout=8000)
        page.click("[data-visit-every='5']")

        # Away through the sidebar, which is a Turbo navigation rather
        # than a load: a load would discard every timer by itself and the
        # check would prove nothing.
        page.click(".dash-side a[href='/dashboard/links']")
        page.wait_for_selector("#links-tbody", timeout=8000)
        before = len(polls)
        page.wait_for_timeout(6000)
        after = len(polls)

        assert after == before, (
            f"{after - before} poll(s) arrived after leaving the page"
        )

    @check("a link's own page charts that link and says where it goes")
    def _():
        page = page_for("/login")
        sign_in(page, base)
        page.goto(f"{base}/dashboard/links/charted01/stats")
        page.wait_for_selector("[data-visit-columns] svg path", timeout=8000)
        # The narrowing has to reach the request, not just the markup: a
        # page that drew the whole account's traffic under one link's code
        # would look right and say something false.
        asked = page.evaluate(
            "async () => (await (await fetch("
            "'/api/v1/stats/visits?scope=mine&period=7d&code=charted01',"
            " {credentials: 'same-origin'})).json()).total"
        )
        whole = page.evaluate(
            "async () => (await (await fetch("
            "'/api/v1/stats/visits?scope=mine&period=7d',"
            " {credentials: 'same-origin'})).json()).total"
        )
        destination = page.inner_text("#link-destination").strip()
        clicks = page.inner_text("#link-clicks").strip()

        assert asked > 0, "the link has no recorded traffic to chart"
        assert asked <= whole, (
            f"one link reports {asked} of the account's {whole}"
        )
        assert "charted" in destination, f"the destination is {destination!r}"
        assert clicks and clicks != "—", "the click counter stayed empty"

    @check("a link's page carries the code into every request it makes")
    def _():
        page = page_for("/login")
        sign_in(page, base)
        asked = []
        page.on("request", lambda request: (
            asked.append(request.url)
            if "/api/v1/stats/visits" in request.url else None
        ))
        page.goto(f"{base}/dashboard/links/charted01/stats")
        page.wait_for_selector("[data-visit-daily] svg", timeout=8000)

        assert len(asked) >= 2, f"expected both charts to fetch, saw {asked}"
        # Including the daily one, which is a second call: a code threaded
        # into one query and not the other draws one chart about this link
        # and one about everything, side by side and unlabelled.
        assert all("code=charted01" in url for url in asked), asked

    @check("a stranger's code on that page shows nothing rather than their traffic")
    def _():
        # The address carries a short code and short codes are guessable,
        # so this page is reachable with somebody else's. What keeps it
        # honest is that the code is always sent with `scope=mine`, which
        # the service applies as one condition with the owner.
        page = page_for("/login")
        sign_in(page, base)
        page.goto(f"{base}/dashboard/links/foreign01/stats")
        page.wait_for_selector("[data-visit-columns] svg", timeout=8000)
        narrowed = page.evaluate(
            "async () => (await (await fetch("
            "'/api/v1/stats/visits?scope=mine&period=7d&code=foreign01',"
            " {credentials: 'same-origin'})).json()).total"
        )
        # The same link asked for service-wide, where this account is an
        # administrator and may look. Both halves are needed: without this
        # one, "zero" would also be the answer for a link nobody has ever
        # opened, and the check would pass while proving nothing.
        service_wide = page.evaluate(
            "async () => (await (await fetch("
            "'/api/v1/stats/visits?scope=service&period=7d&code=foreign01',"
            " {credentials: 'same-origin'})).json()).total"
        )
        marks = page.eval_on_selector_all(
            "[data-visit-columns] svg path", "nodes => nodes.length"
        )

        assert service_wide > 0, "the stranger's link has no traffic to withhold"
        assert narrowed == 0, (
            f"another account's link reported {narrowed} of its "
            f"{service_wide} visits to a stranger"
        )
        assert marks == 0, "the page drew columns for a link that is not this account's"

    @check("the links table offers a way to one link's own page")
    def _():
        # Without this the page exists and nothing leads to it: its address
        # is only reachable by typing a code into the bar.
        page = page_for("/login")
        sign_in(page, base)
        page.goto(f"{base}/dashboard/links")
        page.wait_for_selector(".js-link-stats", timeout=8000)
        page.click(".js-link-stats >> nth=0")
        page.wait_for_selector("[data-visit-code]", timeout=8000)
        code = page.get_attribute("[data-visit-code]", "data-visit-code")

        assert "/stats" in page.url, f"the link went to {page.url}"
        assert code, "the page it opened is not narrowed to any link"

    @check("the chart's axis is written in the language of the page")
    def _():
        # The defect that only a pair of eyes found last time: dates come
        # from `toLocaleDateString`, which formats for the *browser* unless
        # it is handed the page's language. The browser here is en-US, so
        # a chart on a Russian page must not be dotted with slashes.
        page = open_stats(language="ru")
        labels = page.eval_on_selector_all(
            "[data-visit-columns] svg text",
            "nodes => nodes.map(n => n.textContent)"
        )
        dates = [text for text in labels if "." in text or "/" in text]

        assert dates, f"no dates on the axis at all: {labels}"
        assert not any("/" in text for text in dates), (
            f"the axis is written in the browser's locale, not the page's: {dates}"
        )

    @check("a browser that asks for Russian is answered in Russian")
    def _():
        # The seam nothing else in this file touches. Measured before this
        # check existed: Playwright's Chromium sends no `Accept-Language`
        # at all by default -- not `en-US`, nothing -- so every other page
        # in this run takes the "declared nothing" branch and the whole
        # negotiation could be deleted with the run still green. A context
        # with a locale is what makes the browser send the header, and it
        # is the only way to drive that branch through a real browser.
        #
        # Both halves, because they fail apart: `lang` is the decision
        # written down -- it is what a screen reader picks a voice from --
        # and the heading is whether the catalogue was found and read. A
        # page can declare Russian and be written in English, which is what
        # every misconfigured translation directory produces.
        context = browser.new_context(locale="ru-RU")
        try:
            page = context.new_page()
            page.on("console", lambda message: (
                console_errors.append(f"/ (ru-RU): {message.text}")
                if message.type == "error" and not is_a_server_answer(message.text)
                else None
            ))
            page.goto(f"{base}/")
            declared = page.get_attribute("html", "lang")
            heading = page.inner_text("h1").strip()
        finally:
            context.close()

        assert declared == "ru", (
            f"a Russian browser was handed a page declaring {declared!r}"
        )
        assert heading == "Сократить ссылку", (
            f"the page declares Russian and is written in {heading!r}"
        )

    @check("pressing a language redraws the page in it, and it sticks")
    def _():
        # The check the Python suite cannot make. It drives a client with
        # no engine in it, so the control can be perfect in the markup --
        # right ids, right attributes, right hooks -- and dead on the page.
        # That has happened here before, which is why this file exists.
        #
        # Three things in one press, because they fail separately: the
        # handler runs at all, the server is asked again (the words are
        # chosen while the page is built, so nothing but a fresh page can
        # change them), and the choice outlives the navigation.
        page = page_for("/")
        assert page.get_attribute("html", "lang") == "en", (
            "the run started in a language other than the default"
        )

        page.click('.lang-btn[data-lang="ru"]')
        page.wait_for_function(
            "document.documentElement.lang === 'ru'", timeout=5000,
        )

        assert page.get_attribute("html", "lang") == "ru"
        # And the control now says so, which is a separate fault: a page
        # that switched while the control still marks the old language
        # tells the visitor their press did nothing.
        marked = page.get_attribute(".lang-btn--on", "data-lang")
        assert marked == "ru", f"the control still marks {marked!r}"

        # Survives leaving the page. The cookie is the whole mechanism --
        # written by the script, read by the server on the next request --
        # so a press that redrew this page and nothing after it would be
        # the failure that matters most.
        page.goto(f"{base}/login")
        assert page.get_attribute("html", "lang") == "ru", (
            "the choice did not survive a navigation"
        )

    @check("the language control still works after a Turbo navigation")
    def _():
        # The failure this file was built for, in its exact shape. Turbo
        # replaces the whole `<body>` on a navigation, so a handler bound
        # to the control instead of to `document` dies with the body it was
        # bound to -- and the control keeps its markup, its class and its
        # `data-lang`, and does nothing. The check above cannot see it: it
        # presses on a freshly loaded page, where a per-element handler
        # would still be alive.
        page = page_for("/")

        # A marker on `window`, which a Turbo visit keeps and a full load
        # discards. Without it this check would still pass if the link
        # happened to reload the page, and it would then be testing the
        # same thing as the check above.
        page.evaluate("() => { window.__stillTheSameDocument = true; }")
        page.click('.header-link[href="/login"]')
        page.wait_for_selector(".lang-switch", timeout=5000)

        assert page.evaluate("() => window.__stillTheSameDocument === true"), (
            "that was a full load, not a Turbo visit -- the check proves nothing"
        )

        page.click('.lang-btn[data-lang="ru"]')
        page.wait_for_function(
            "document.documentElement.lang === 'ru'", timeout=5000,
        )

        assert page.get_attribute("html", "lang") == "ru"

    def in_russian(page):
        """
        Put this browser into Russian and load the page again.

        Through the cookie, which is the mechanism a visitor's choice uses
        and the one that outranks ``Accept-Language``. Set on the context
        rather than by pressing the control, so that a check about what a
        script writes cannot fail for a reason belonging to the switch.

        Args:
            page: An open page; it is reloaded in place.
        """
        page.context.add_cookies([{
            "name": "lang", "value": "ru", "url": base,
        }])
        page.reload()

    @check("a refusal a script prints is in the language of the page")
    def _():
        # The seam this whole mechanism exists for, and the one nothing
        # else in this file could see. The page arrives in Russian and the
        # script then writes its own sentence into it -- from a string that
        # used to be typed into the `.js` file in English, on every page,
        # in every language. `fetch` is made to throw, which is the branch
        # that reaches for the script's own words rather than repeating the
        # service's.
        # Its own page, opened without the console collector: the network
        # is cut on purpose here, and the browser reports that as an error
        # like any other. Collecting it would make the last check in this
        # file fail for a thing this one arranged.
        #
        # The cut is made with `route`, not by replacing `window.fetch`. A
        # replaced `fetch` belongs to the document it was written into, and
        # the reload that follows builds a new one -- so the script runs
        # against the real network and the table fills in normally, which
        # looks exactly like a check that passed.
        page = browser.new_page()
        page.goto(f"{base}/login")
        sign_in(page, base)
        page.context.add_cookies([{"name": "lang", "value": "ru", "url": base}])
        page.route("**/api/v1/links/mine", lambda route: route.abort())
        page.goto(f"{base}/dashboard/links")
        page.wait_for_function(
            "document.getElementById('links-error').textContent.trim() !== ''",
            timeout=5000,
        )
        shown = page.inner_text("#links-error").strip()

        assert shown == "Служба недоступна.", (
            f"the page is Russian and its script wrote {shown!r}"
        )

    @check("a table a script draws is drawn in the language of the page")
    def _():
        # The other half, and it fails apart from the one above: an error
        # path and a success path reach different strings, and the sixteen
        # sentences this project had buried inside concatenated markup --
        # `'<td>...Delete</button></td>'` -- were all on the success path.
        page = page_for("/login")
        sign_in(page, base)
        page.goto(f"{base}/dashboard/links")
        page.wait_for_selector("#links-tbody .del-btn", timeout=5000)
        in_russian(page)
        page.wait_for_selector("#links-tbody .del-btn", timeout=5000)
        caption = page.inner_text("#links-tbody .del-btn")

        assert caption.strip() == "Удалить", (
            f"the page is Russian and the button a script drew says {caption!r}"
        )

    @check("the question before a delete is asked in the language of the page")
    def _():
        # Includes the substitution, which is the part a dictionary of
        # plain strings cannot carry: the sentence names the code, and a
        # translator has to be able to move that name to the other end of
        # it. What the browser shows is what is checked -- the value
        # travels through `t()` into a real `confirm()`.
        page = page_for("/login")
        sign_in(page, base)
        page.goto(f"{base}/dashboard/links")
        page.wait_for_selector("#links-tbody .del-btn", timeout=5000)
        in_russian(page)
        page.wait_for_selector("#links-tbody .del-btn", timeout=5000)
        code = page.get_attribute("#links-tbody .del-btn", "data-code")

        asked = []

        def remember(dialog):
            """Take the question down and answer no, so nothing is lost."""
            asked.append(dialog.message)
            dialog.dismiss()

        page.on("dialog", remember)
        page.click("#links-tbody .del-btn")

        assert asked, "the delete button asked nothing before deleting"
        assert asked[0] == f"Удалить ссылку {code}?", (
            f"the page is Russian and the question was {asked[0]!r}"
        )

    @check("a date is written in the language of the page, not the browser's")
    def _():
        # The fault no scan can find, because it produces no text: a script
        # calling `toLocaleDateString()` with no argument formats for the
        # browser's locale. A reader who picked Russian on an en-US browser
        # got `8/16/2026` under a column headed "Создана".
        #
        # The context is given `locale="en-US"` on purpose, so the two
        # cannot agree by accident: the browser is English, the cookie says
        # Russian, and the date has to follow the cookie.
        context = browser.new_context(locale="en-US")
        try:
            page = context.new_page()
            page.on("console", lambda message: (
                console_errors.append(f"/dashboard/links (en-US): {message.text}")
                if message.type == "error" and not is_a_server_answer(message.text)
                else None
            ))
            page.goto(f"{base}/login")
            sign_in(page, base)
            context.add_cookies([{"name": "lang", "value": "ru", "url": base}])
            page.goto(f"{base}/dashboard/links")
            page.wait_for_selector("#links-tbody tr td", timeout=5000)
            # Fourth column is "Создана"; the row is drawn by the script.
            written = page.inner_text("#links-tbody tr td:nth-child(4)").strip()
        finally:
            context.close()

        assert re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", written), (
            f"the page is Russian and the date reads {written!r} -- "
            "Russian writes 16.08.2026, en-US writes 8/16/2026"
        )

    @check("the journal page shows records, not an empty table")
    def _():
        # This whole page is drawn by a script from an endpoint, so a test
        # client can prove the endpoint answers and nothing else: whether
        # any of it reaches the screen is only answerable in a browser.
        grant_role(app, "browser-user@example.test", "auditor")
        page = page_for("/login")
        sign_in(page, base)
        page.goto(f"{base}/dashboard/service/journals")
        page.wait_for_selector("[data-journal-row]", timeout=5000)

        first = page.inner_text("[data-journal-row] .journal-time").strip()
        assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", first), first
        # The label under the table, which is what keeps the oldest line on
        # screen from reading as the beginning of history.
        said = page.inner_text("[data-journal-reach]").strip()
        assert "application.log" in said, said
        # The label is a list of pieces, and they used to be joined by a
        # space: the first ends in a file name rather than a full stop, so
        # it read "Lines: 200 · application.log Older lines exist." -- two
        # sentences run together, in Russian as well.
        assert "log Older" not in said, said
        assert " · " in said, said

    @check("choosing another journal reads that journal")
    def _():
        # The three buttons are the page's only navigation, and each one is
        # a different permission behind the same address -- a button that
        # silently kept showing the previous journal would be the most
        # convincing possible way to get an audit read wrong.
        page = page_for("/login")
        sign_in(page, base)
        page.goto(f"{base}/dashboard/service/journals")
        page.wait_for_selector("[data-journal-row]", timeout=5000)
        page.click('[data-journal="audit"]')
        page.wait_for_function(
            "document.querySelector('[data-journal-reach]')"
            ".textContent.indexOf('audit.log') !== -1",
            timeout=5000,
        )

        assert page.inner_text("[data-journal-title]").strip().lower() == "audit"

    @check("a record opens to show the line as it was written")
    def _():
        # Everything on a row is a rendering; an operator reconstructing an
        # incident eventually needs the bytes. The raw line is a sibling row
        # that starts hidden, and `hidden` is a class -- so a stylesheet
        # that lost the rule would leave every raw line permanently open,
        # which this catches from the other direction too.
        page = page_for("/login")
        sign_in(page, base)
        page.goto(f"{base}/dashboard/service/journals")
        page.wait_for_selector("[data-journal-row]", timeout=5000)
        assert page.locator(".journal-expanded:not(.hidden)").count() == 0

        page.click("[data-journal-row]")
        page.wait_for_selector(".journal-expanded:not(.hidden)", timeout=5000)

        raw = page.inner_text(".journal-expanded:not(.hidden) .journal-raw")
        assert raw.strip().startswith("{"), raw[:80]

    @check("a reader watching the tail is still watching it after a poll")
    def _():
        # The table scrolls inside its own box, and new lines arrive at the
        # bottom of it. Somebody who has scrolled down to watch the tail is
        # therefore left behind by every poll unless the box is moved for
        # them: measured with the follow removed, two polls at five seconds
        # put the tail 204 pixels below the last line on screen.
        #
        # Only this half is checked, because only this half is code. A
        # reader stopped partway keeps their place without help --
        # replacing the rows leaves `scrollTop` alone -- and a check on
        # that would be a check on the browser, green whatever this page
        # does.
        page = page_for("/login")
        sign_in(page, base)
        page.goto(f"{base}/dashboard/service/journals")
        page.wait_for_selector("[data-journal-row]", timeout=5000)
        page.click('[data-journal-lines="1000"]')
        page.click('[data-journal-every="5"]')
        page.wait_for_timeout(1000)

        page.evaluate(
            "var box = document.querySelector('[data-journal-scroll]');"
            "box.scrollTop = box.scrollHeight;"
        )
        # Long enough for two polls, each of which adds the requests this
        # very page just made.
        page.wait_for_timeout(12000)
        behind = page.evaluate(
            "var box = document.querySelector('[data-journal-scroll]');"
            "box.scrollHeight - box.clientHeight - box.scrollTop"
        )

        assert behind < 40, f"the tail ran {behind} pixels ahead of the reader"

    @check("no page reported a script error to the console")
    def _():
        # Anything the browser itself could not run, and any answer a
        # script asked for and did not get. A 401 from a probe the page
        # makes on purpose would show up here too, which is why the sign-in
        # checks above go through the form rather than the API.
        assert console_errors == [], console_errors


if __name__ == "__main__":
    sys.exit(main())
