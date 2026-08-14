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


def build_app(database_path: Path, base_url: str, mail_port: int):
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


def promote_to_admin(app, email: str) -> None:
    """
    Give an account the admin role, the way an operator makes the first one.

    There is no endpoint for this and there should not be: the first
    administrator cannot be appointed by an administrator. The row is
    written directly, which is what ``smoke_test.py`` does for the same
    reason.

    Args:
        app: The running application.
        email: Address of the account to promote.
    """
    from sqlalchemy import text

    with app.app_context():
        with app.container.get_db_manager().session() as session:
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
        app = build_app(Path(workspace) / "browser.db", base, mail.port)
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
    expected = 15
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

    def page_for(path: str):
        """Open a page and collect its console errors."""
        page = browser.new_page()
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
        promote_to_admin(app, "browser-user@example.test")
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
        # network looked identical to the person waiting. Measured by
        # asking for a page whose data this account may not have: the
        # account below holds no administrative permission, so the users
        # page answers 403 to the markup and the script has to say it.
        #
        # Restoring the silent return in any page script turns this red,
        # which is what the run above could not do.
        page = page_for("/login")
        sign_in(page, base)
        page.goto(f"{base}/dashboard/links")
        page.wait_for_selector("#links-tbody tr", timeout=5000)
        page.evaluate("() => { window.fetch = async () => new Response("
                      "JSON.stringify({message: 'Not authorized'}), {status: 403}); }")
        page.reload()
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

    @check("no page reported a script error to the console")
    def _():
        # Anything the browser itself could not run, and any answer a
        # script asked for and did not get. A 401 from a probe the page
        # makes on purpose would show up here too, which is why the sign-in
        # checks above go through the form rather than the API.
        assert console_errors == [], console_errors


if __name__ == "__main__":
    sys.exit(main())
