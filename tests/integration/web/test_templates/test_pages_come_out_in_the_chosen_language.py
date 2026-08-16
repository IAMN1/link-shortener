"""
Pages rendered through the real catalogues, in each language on offer.

``tests/unit/web/test_translations.py`` reads the catalogue files and says
they are complete, compiled and current. That is a statement about files.
This is the other half: that the wiring between a request and those files
holds -- the selector picks a language, Flask-Babel finds the catalogue for
it on disk, and the words on the page change.

Every one of those can break on its own and leave a page that renders, in
English, with a fully translated catalogue in the repository:
``BABEL_TRANSLATION_DIRECTORIES`` pointing somewhere else, the extension
registered after the first render, a locale selector answering a tag no
directory is named after.

Checked by reading the page back rather than by asking Babel, because
asking Babel is asking the thing under test.
"""

import re
from unittest.mock import Mock

import pytest
from flask import g, render_template


def rendered(app, template, language, **context):
    """
    Draw a page as a visitor who chose this language gets it.

    ``g.authorization_service`` is put in place by hand because
    ``test_request_context`` runs no middleware, and every block guarded by
    ``can(...)`` asks that service. Without it ``can`` answers False for
    everything and the guarded blocks are simply absent -- which is how the
    two checks on the quota line first passed against a page that never
    drew it.

    Args:
        app: The application under test.
        template: Template to render.
        language: Language tag to put in the cookie.
        **context: What the view would pass in. Named by the caller rather
            than defaulted here, for the same reason: a block that renders
            only when its variable is present is a block a test can
            silently skip.

    Returns:
        The page's markup.
    """
    allows_everything = Mock()
    allows_everything.is_allowed.return_value = True

    with app.test_request_context("/", headers={"Cookie": f"lang={language}"}):
        g.authorization_service = allows_everything
        return render_template(template, **context)


QUOTA = {"guest_link_limit": 10, "guest_ttl_days": 7}
"""What the landing page's view passes so the quota line is drawn.

The defaults the service ships with -- ten links a day, seven days each.
Ten is not an arbitrary choice for the plural check: in Russian it takes
the third form, which is the one a naive ``if n == 1`` never reaches.
"""


def heading(markup):
    """Pull the first heading out of a page."""
    found = re.search(r"<h1[^>]*>(.*?)</h1>", markup, re.S)
    return re.sub(r"<[^>]+>", "", found.group(1)).strip() if found else None


# The landing page's heading, in each language. Written out here rather than
# looked up through `gettext`: a test that asks the catalogue what the
# catalogue says would pass against an empty one.
EXPECTED_HEADING = {
    "en": "Shorten a link",
    "ru": "Сократить ссылку",
    "zh": "缩短链接",
}


class TestTheWordsOnThePageChange:

    @pytest.mark.parametrize("language,expected", sorted(EXPECTED_HEADING.items()))
    def test_the_landing_page_is_written_in_the_chosen_language(
        self, app, language, expected
    ):
        assert heading(rendered(app, "public/index.html", language)) == expected

    def test_english_needs_no_catalogue_of_its_own(self, app):
        """
        There is no ``translations/en``, and there should not be: an
        untranslated ``gettext`` call answers its own msgid, and the msgids
        are the English text. A catalogue for English would be a second
        copy of every string, free to drift from the first.
        """
        markup = rendered(app, "public/index.html", "en")

        assert "Shorten a link" in markup

    def test_a_language_nobody_offers_falls_back_rather_than_failing(self, app):
        """
        The selector refuses an unknown tag before Babel ever sees it, so
        this never reaches a missing directory. Held because the failure it
        guards against is not a 500 -- Babel answers the msgid for a
        catalogue it cannot find, so the page would render in English and
        the fault would be invisible.
        """
        assert heading(rendered(app, "public/index.html", "xx")) == "Shorten a link"


class TestThePlacesTranslationIsEasiestToLose:

    def test_a_string_from_the_shared_layout_is_translated(self, app):
        """
        The layout is rendered through `extends`, one template deeper than
        the page. Its strings reach the catalogue by the same route, but
        the extraction config has to match the layout's path as well as
        the page's -- and a glob that missed the layout would leave the
        header English on every page at once.
        """
        markup = rendered(app, "public/index.html", "ru")

        assert "Войти" in markup, "the header is still in English"

    def test_a_string_from_an_included_partial_is_translated(self, app):
        """
        The language control is an `include`, which is a third route into
        the page. Its own label is the one string on the page a visitor
        who cannot read the interface needs most.
        """
        markup = rendered(app, "public/index.html", "ru")

        assert 'aria-label="Язык интерфейса"' in markup

    def test_a_plural_takes_the_form_the_number_calls_for(self, app):
        """
        The reason gettext was chosen over a dictionary of strings. Russian
        has three forms and the rule that picks between them is arithmetic
        on the number -- ten takes the third, which is the one a naive
        `if n == 1` would never reach.
        """
        markup = rendered(app, "public/index.html", "ru", **QUOTA)

        # Read with the markup taken out: the number is wrapped in `<b>`,
        # so the sentence never appears as one run of characters in the
        # source. Asserting on the raw markup failed here for that reason
        # and not for the reason the check is about.
        words = re.sub(r"<[^>]+>", "", markup)

        assert "10 ссылок в день" in words, (
            "the plural came out in the wrong form"
        )
        assert "7 дней" in words, "the second plural came out in the wrong form"

    def test_one_english_word_can_have_two_translations(self, app):
        """
        "Sign up" is a button in the header and a verb inside a sentence.
        English is content with one word for both; Russian is not. The two
        are separated by a message context, and this holds that the context
        is still reaching the catalogue -- lose it and both places quietly
        collapse onto whichever translation was written first.
        """
        markup = rendered(app, "public/index.html", "ru", **QUOTA)

        assert "Регистрация" in markup, "the header's button lost its own wording"
        assert "Зарегистрируйтесь" in markup, "the sentence lost its own wording"


class TestTheMarkupAroundTheWordsSurvives:

    def test_a_translated_sentence_keeps_the_link_inside_it(self, app):
        """
        Sentences with a link in them are translated whole, with the link
        substituted in, so a translator can move it. The substitution is
        the part that breaks: escaped rather than inserted, the visitor
        reads the raw `<a href=...>` in the middle of a sentence.
        """
        markup = rendered(app, "public/index.html", "ru")

        assert "&lt;a href" not in markup, "a link was escaped into the text"
        assert re.search(r"Ни SDK[^<]*<a href=", markup), (
            "the sentence lost the link it was built around"
        )
