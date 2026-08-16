"""
Tests that a rendered page declares the language it was written in.

``<html lang>`` was the string ``en``, hard-coded, and it was the only place
in the service where a language was named at all. A page whose text is
Russian and whose ``lang`` still says English is not a cosmetic fault: it is
what a screen reader uses to choose a voice, what a browser uses to offer a
translation, and what hyphenation is picked by.

Rendered through the real template rather than asserted against the file,
because the defect this guards against is the attribute falling back to a
literal -- which a file read would happily confirm as correct.

The other half, that the language reaches the catalogue as well as the
attribute, is held by ``tests/unit/web/test_i18n.py``: both come from one
function, and these tests are what keeps the layout asking it.
"""

from flask import render_template


def rendered(app, cookie=None, accept=None):
    """
    Draw the landing page the way a visitor with these preferences gets it.

    Args:
        app: The application under test.
        cookie: Value of the language cookie, or None to send none.
        accept: ``Accept-Language`` header, or None to send none.

    Returns:
        The page's markup.
    """
    headers = {}
    if cookie is not None:
        headers["Cookie"] = f"lang={cookie}"
    if accept is not None:
        headers["Accept-Language"] = accept

    with app.test_request_context("/", headers=headers):
        return render_template("public/index.html")


class TestTheAttributeFollowsTheChoice:

    def test_a_visitor_who_declared_nothing_gets_english(self, app):
        assert '<html lang="en"' in rendered(app)

    def test_a_russian_browser_gets_a_russian_page(self, app):
        assert '<html lang="ru"' in rendered(app, accept="ru-RU,ru;q=0.9,en;q=0.8")

    def test_a_chinese_browser_gets_a_chinese_page(self, app):
        assert '<html lang="zh"' in rendered(app, accept="zh-CN,zh;q=0.9")

    def test_the_cookie_outranks_the_browser(self, app):
        assert '<html lang="ru"' in rendered(app, cookie="ru", accept="en-US")

    def test_a_language_nobody_offers_falls_back_to_english(self, app):
        assert '<html lang="en"' in rendered(app, accept="fr-FR,fr;q=0.9")


class TestTheAttributeIsNoLongerALiteral:

    def test_the_layout_does_not_carry_a_hard_coded_language(self, app):
        """
        The guard that matters. Every assertion above still passes if the
        attribute is printed from a variable that happens to hold "en", and
        every one of them fails only for the language they name -- so a
        layout that reverted to ``lang="en"`` would fail four tests and be
        fixed by re-hardcoding it. This one fails for the reversion itself.
        """
        import pathlib

        import link_shortener.web

        layout = (
            pathlib.Path(link_shortener.web.__file__).parent
            / "templates" / "layout" / "base.html"
        ).read_text(encoding="utf-8")

        assert '<html lang="en"' not in layout
        assert '<html lang="{{ current_language }}"' in layout


class TestTheThemeStillSurvivesBesideIt:
    """
    The two attributes share one tag, and the language was added to it.

    Worth its own check because the edit that adds a language is exactly
    the edit that can drop the theme: both are conditional pieces of the
    same ``<html>`` line, and a page that forgets the theme paints the
    wrong colours from the first frame on every navigation.
    """

    def test_the_theme_is_still_stamped(self, app):
        with app.test_request_context("/", headers={"Cookie": "theme=dark; lang=ru"}):
            markup = render_template("public/index.html")

        assert '<html lang="ru" data-theme="dark"' in markup

    def test_no_theme_cookie_still_stamps_nothing(self, app):
        """
        Absent the cookie the stylesheet falls through to
        ``prefers-color-scheme``, which is the state most visitors are in.
        """
        markup = rendered(app)

        assert "data-theme" not in markup
