"""The journal page's markup, and its agreement with the script.

Nothing here runs the page -- the reading happens in a browser, and
``tests/live/browser_test.py`` is where that is measured. What is checked is
the seam: the template offers journals, line counts and intervals as
``data-`` attributes, ``static/js/journals.js`` reads them and decides what
is valid, and the two lists live in different files in different languages.
An interval the template offers and the script rejects is a button that
silently does nothing.

The other half is the permission split, rendered. Which journals a caller
is offered is decided in the markup by ``can``, and getting that wrong is
not a security fault -- the endpoint refuses regardless -- but it is a page
that either hides a journal somebody may read or offers one they may not,
and the second reads as the service being broken rather than as them being
unentitled.
"""

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import g, render_template

from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.web.app_factory import create_app


WEB = Path(__file__).resolve().parents[3] / "src" / "link_shortener" / "web"
JOURNALS_JS = WEB / "static" / "js" / "journals.js"


@pytest.fixture
def journals_app():
    """
    A real application, with its real templates.

    Deliberately not named ``app``: ``tests/unit/web/conftest.py`` carries
    an autouse fixture that swaps the Jinja loader for one answering
    "Rendered <name>" to everything, and it takes its argument by that
    name. A test about markup that quietly measured that stub would pass
    whatever the template said.

    Handed back without an application context around it, deliberately.
    ``can`` memoises its answers on ``g``, and ``g`` belongs to the
    application context rather than to the request -- so a context held
    open across two renders carries the first caller's permissions into
    the second, and a test comparing what two callers are offered compares
    one caller with itself. Each render below opens its own.
    """
    return create_app(config=TestingConfig())


def render_page(application, permissions):
    """
    Render the journal page as a caller holding certain permissions.

    Args:
        application: The application whose Jinja environment to use.
        permissions: Permission names the caller holds.

    Returns:
        The rendered markup.
    """
    class Allows:
        """Answers ``can`` from a fixed set rather than from a database."""

        @staticmethod
        def is_allowed(_user, permission):
            return permission in permissions

    # Through ``render_template`` rather than the Jinja environment
    # directly: the layout this page extends reads what the context
    # processors provide -- the language menu, the permission helper -- and
    # a template rendered around Flask rather than through it fails on the
    # first of them.
    # Signed in, because ``dashboard/base.html`` draws nothing at all
    # without a caller -- the page's content sits inside that check. A
    # render with ``g.current_user`` left unset comes back as a shell, and
    # every assertion about the markup would pass over an empty string
    # rather than over the page.
    with application.test_request_context("/dashboard/service/journals"):
        g.current_user = SimpleNamespace(
            id="reader-1", email="reader@example.test", roles=["auditor"]
        )
        g.authorization_service = Allows()
        return render_template("dashboard/journals.html")


def offered_journals(markup):
    """
    The journals the page offers as buttons.

    Args:
        markup: The rendered page.

    Returns:
        List of journal names, in the order they appear.
    """
    return re.findall(r'data-journal="([a-z]+)"', markup)


class TestOnlyTheJournalsThisCallerMayReadAreOffered:

    def test_logs_view_offers_the_operational_journals_and_not_the_record(
        self, journals_app
    ):
        markup = render_page(journals_app, {"logs:view"})

        assert offered_journals(markup) == ["application", "error"]

    def test_audit_view_offers_the_record_and_not_the_others(
        self, journals_app
    ):
        markup = render_page(journals_app, {"audit:view"})

        assert offered_journals(markup) == ["audit"]

    def test_holding_both_offers_all_three(self, journals_app):
        markup = render_page(journals_app, {"logs:view", "audit:view"})

        assert offered_journals(markup) == ["application", "error", "audit"]

    def test_what_the_journals_carry_is_said_to_whoever_reads_the_record(
        self, journals_app
    ):
        """
        The warning is shown to the caller who can open the audit journal,
        and it names both journals rather than only that one: the
        application journal carries the address of everyone who signed in,
        which is the fact least likely to be guessed from a page of
        timestamps.
        """
        reader = render_page(journals_app, {"audit:view"})
        operator = render_page(journals_app, {"logs:view"})

        assert "audit journal names destination addresses" in reader
        assert "application journal names the address" in reader
        assert "audit journal names destination addresses" not in operator


class TestTheMarkupCarriesWhatTheScriptLooksFor:

    def test_every_hook_the_script_reads_is_in_the_markup(self, journals_app):
        """
        The script asks for these by attribute and skips what it cannot
        find, so a renamed hook removes a control with no error anywhere:
        the button stays inert and the page still loads.
        """
        markup = render_page(journals_app, {"logs:view", "audit:view"})
        script = JOURNALS_JS.read_text(encoding="utf-8")

        # ``data-journal-row`` is left out: the script writes that one
        # itself, on the rows it draws, and looking for it in the template
        # would be looking for markup that only exists once a journal has
        # been fetched.
        drawn_by_the_script = {"data-journal-row"}
        wanted = set(
            re.findall(r"\[(data-journal[a-z-]*)[\]=]", script)
        ) - drawn_by_the_script
        missing = sorted(hook for hook in wanted if hook not in markup)

        assert wanted, "no hooks were found in journals.js -- the pattern stopped matching"
        assert missing == [], (
            f"journals.js reads these and the template does not offer them: {missing}"
        )

    def test_the_intervals_offered_are_the_intervals_the_script_accepts(
        self, journals_app
    ):
        """
        An interval the script rejects is a button that resets itself to
        ten seconds without saying so.
        """
        markup = render_page(journals_app, {"logs:view"})
        script = JOURNALS_JS.read_text(encoding="utf-8")

        offered = {
            int(value)
            for value in re.findall(r'data-journal-every="(\d+)"', markup)
        }
        accepted = {
            int(value) for value in re.findall(
                r"JOURNAL_INTERVALS = \[([\d, ]+)\]", script
            )[0].split(",")
        }

        assert offered == accepted

    def test_the_line_counts_offered_are_the_ones_the_script_accepts(
        self, journals_app
    ):
        markup = render_page(journals_app, {"logs:view"})
        script = JOURNALS_JS.read_text(encoding="utf-8")

        offered = {
            int(value)
            for value in re.findall(r'data-journal-lines="(\d+)"', markup)
        }
        accepted = {
            int(value) for value in re.findall(
                r"JOURNAL_LINE_COUNTS = \[([\d, ]+)\]", script
            )[0].split(",")
        }

        assert offered == accepted

    def test_no_line_count_exceeds_what_the_service_will_serve(
        self, journals_app
    ):
        """
        A button asking for more than the ceiling is a button that answers
        400 every time it is pressed -- and the page would show the
        refusal rather than the journal.
        """
        from link_shortener.infrastructure.logging.journal_reader import (
            HARD_LIMIT,
        )

        markup = render_page(journals_app, {"logs:view"})
        offered = [
            int(value)
            for value in re.findall(r'data-journal-lines="(\d+)"', markup)
        ]

        assert offered
        assert max(offered) <= HARD_LIMIT

    def test_the_page_loads_the_file_that_owns_the_timer(self, journals_app):
        """
        ``journals.js`` from the head and ``pages/journals.js`` from the
        body, which is what keeps one timer per tab rather than one per
        navigation.
        """
        markup = render_page(journals_app, {"logs:view"})

        assert "js/journals.js" in markup
        assert "js/pages/journals.js" in markup
