"""
The control that changes the language, as it is drawn on a real page.

Rendered rather than read off disk, because the faults worth catching are
the ones a file read confirms as correct: a control that never marks a
current language, a control drawn on one layout and not the other, a
control whose accessible name is the tag rather than the language.

What this cannot see is whether pressing it does anything -- the Python
suite drives a client with no engine in it, so a control can be perfect
here and dead in a browser. ``tests/live/browser_test.py`` presses it.
"""

import re

from flask import g, render_template
from unittest.mock import Mock


def control_from(markup):
    """
    Pull the language control out of a rendered page.

    Args:
        markup: The whole page.

    Returns:
        The control's markup, or None when the page carries none.
    """
    found = re.search(r'<div class="lang-switch".*?</div>', markup, re.S)
    return found.group(0) if found else None


def segments(markup):
    """
    Read the control back as data.

    Args:
        markup: The whole page.

    Returns:
        List of ``(tag, label, accessible_name, is_current)``.
    """
    control = control_from(markup) or ""
    out = []
    for button in re.finditer(r"<button[^>]*>[^<]*</button>", control):
        html = button.group(0)
        tag = re.search(r'data-lang="([^"]+)"', html)
        name = re.search(r'aria-label="([^"]+)"', html)
        label = re.search(r">([^<]*)</button>", html)
        out.append((
            tag.group(1) if tag else None,
            (label.group(1) if label else "").strip(),
            name.group(1) if name else None,
            'aria-current="true"' in html,
        ))
    return out


def public_page(app, cookie=None, accept=None):
    """Draw the landing page as a visitor with these preferences gets it."""
    headers = {}
    if cookie is not None:
        headers["Cookie"] = f"lang={cookie}"
    if accept is not None:
        headers["Accept-Language"] = accept

    with app.test_request_context("/", headers=headers):
        return render_template("public/index.html")


def dashboard_page(app):
    """Draw a dashboard page, which uses the other layout."""
    user = Mock()
    user.id = "11111111-1111-1111-1111-111111111111"
    user.email = "someone@example.com"
    user.roles = ["admin"]

    allows_everything = Mock()
    allows_everything.is_allowed.return_value = True

    with app.test_request_context("/dashboard/"):
        g.current_user = user
        g.authorization_service = allows_everything
        return render_template("dashboard/home.html")


class TestTheControlIsOnEveryHeader:

    def test_the_public_pages_carry_it(self, app):
        assert control_from(public_page(app)) is not None

    def test_the_dashboard_carries_it_too(self, app):
        """
        The two headers are separate templates and have drifted before --
        the dashboard's own sidebar once repeated destinations the public
        header carried. A visitor who signs in must not lose the control.
        """
        assert control_from(dashboard_page(app)) is not None


class TestEveryOfferedLanguageIsOffered:

    def test_one_segment_per_configured_language(self, app):
        tags = [tag for tag, _, _, _ in segments(public_page(app))]

        assert tags == ["en", "ru", "zh"]

    def test_the_label_is_the_tag_in_capitals(self, app):
        labels = [label for _, label, _, _ in segments(public_page(app))]

        assert labels == ["EN", "RU", "ZH"]

    def test_the_accessible_name_is_the_language_in_its_own_words(self, app):
        """
        What somebody hunting for their language recognises is `русский`,
        not `Russian` -- and certainly not `ru`. Taken from Babel rather
        than from a table here, so adding a language needs one edit and not
        two.
        """
        names = [name for _, _, name, _ in segments(public_page(app))]

        assert names == ["English", "русский", "中文"]

    def test_a_narrowed_configuration_narrows_the_control(self, monkeypatch, app):
        """
        Through ``monkeypatch`` and not by assignment. The ``app`` fixture
        here is ``scope="session"`` -- one application for the whole run --
        so a plain write to its config outlives the test and every later
        one renders against it. Written that way first, and what it broke
        was the check below that a chosen `zh` is marked: `zh` was no
        longer among the offered languages, so the cookie was correctly
        ignored and the failure looked like a defect in the cookie.
        """
        monkeypatch.setitem(app.config, "SUPPORTED_LANGUAGES", ["en", "ru"])

        tags = [tag for tag, _, _, _ in segments(public_page(app))]

        assert tags == ["en", "ru"]


class TestTheControlSaysWhichLanguageIsInForce:

    def test_the_default_is_marked(self, app):
        current = [tag for tag, _, _, on in segments(public_page(app)) if on]

        assert current == ["en"]

    def test_the_negotiated_language_is_marked(self, app):
        page = public_page(app, accept="ru-RU,ru;q=0.9")
        current = [tag for tag, _, _, on in segments(page) if on]

        assert current == ["ru"]

    def test_the_chosen_language_is_marked(self, app):
        page = public_page(app, cookie="zh")
        current = [tag for tag, _, _, on in segments(page) if on]

        assert current == ["zh"]

    def test_exactly_one_is_ever_marked(self, app):
        """
        Two marked segments would be the sign that the control is comparing
        against something other than the answer the page was built from.
        """
        for kwargs in ({}, {"accept": "ru-RU"}, {"cookie": "zh"},
                       {"cookie": "xx", "accept": "ru"}):
            marked = [tag for tag, _, _, on in segments(public_page(app, **kwargs)) if on]

            assert len(marked) == 1, f"{kwargs} marked {marked}"

    def test_the_marked_one_agrees_with_the_page(self, app):
        """
        The control and ``<html lang>`` are drawn from the same call, and
        this is what keeps it that way: a control that marked one language
        while the page declared another would be telling the visitor their
        press did nothing.
        """
        page = public_page(app, accept="zh-CN,zh;q=0.9")
        declared = re.search(r'<html lang="([^"]+)"', page).group(1)
        marked = [tag for tag, _, _, on in segments(page) if on]

        assert marked == [declared]


class TestTheMarkedSegmentStaysReachable:

    def test_it_is_not_disabled(self, app):
        """
        Disabling the current language takes it out of the tab order, and
        then somebody moving by keyboard has no way to find out which
        language they are already in. The press is refused in the handler,
        where refusing is free.
        """
        control = control_from(public_page(app))

        assert "disabled" not in control
