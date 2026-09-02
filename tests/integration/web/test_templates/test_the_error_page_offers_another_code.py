"""
The lookup form under a dead short code, and what decides it is there.

A code that leads nowhere is the ordinary business of a link shortener, so
``error.html`` puts a form for trying another one under that refusal, and
plain text under every other. Nothing checked that until this file: the
suite was green with the form present, and it would have stayed green with
the form gone.

Which is the failure worth guarding. The page used to decide by reading its
own sentence -- ``'link' in error|lower`` -- so the form appeared for
"Link not found" and vanished for "Ссылка не найдена". A 404 page that
loses its recovery form is not a page that breaks; it is a page that draws
perfectly and helps nobody, on the language most likely to need help.

Both levels are held here: that ``error_page`` decides by code rather than
by wording, and that the handlers behind the real routes hand it the right
code. Either alone passes over the other's break.
"""

import pytest
from flask import g
from unittest.mock import Mock

from link_shortener.web.responses import error_page


LOOKUP_FORM = 'id="form-info"'
"""The form's own id -- what its absence has to be measured by.

The heading and the paragraph move with the translation; this does not.
"""


def drawn(app, code, message):
    """
    Draw the error page the way ``error_page`` draws it for a refusal.

    ``g.authorization_service`` is put in place by hand because
    ``test_request_context`` runs no middleware, and the shared layout asks
    that service through ``can(...)``. Without it the page still renders --
    which is exactly how a check on a block that was never drawn passes.

    Args:
        app: The application under test.
        code: Machine-readable error code, as a handler would pass it.
        message: The sentence for a human.

    Returns:
        The page's markup.
    """
    allows_everything = Mock()
    allows_everything.is_allowed.return_value = True

    with app.test_request_context("/nosuchcode"):
        g.authorization_service = allows_everything
        markup, _status = error_page(code, message, 404)
        return markup


class TestWhichRefusalsOfferALookup:

    @pytest.mark.parametrize("code", ["LINK_NOT_FOUND", "LINK_EXPIRED"])
    def test_a_dead_code_is_answered_with_a_way_to_try_another(self, app, code):
        """
        Both of them: a code that never existed and one that has run out
        are the same situation for the visitor holding it.
        """
        assert LOOKUP_FORM in drawn(app, code, "Link not found")

    @pytest.mark.parametrize(
        "code", ["NOT_FOUND", "FORBIDDEN", "BAD_REQUEST", "INTERNAL_SERVER_ERROR"]
    )
    def test_every_other_refusal_offers_plain_text(self, app, code):
        """
        A missing page, a refusal and a crash have nothing to do with
        short codes, and a form asking for one under them is noise.
        """
        assert LOOKUP_FORM not in drawn(app, code, "Page not found")

    def test_the_form_survives_a_sentence_with_no_english_in_it(self, app):
        """
        The check this file exists for.

        Reading the sentence, this is exactly the case that failed: no
        ``link`` anywhere in "Ссылка не найдена", so the form went away on
        the Russian page and stayed on the English one. Deciding by code,
        the wording is free to be anything.
        """
        markup = drawn(app, "LINK_NOT_FOUND", "Ссылка не найдена")

        assert LOOKUP_FORM in markup

    def test_a_page_about_short_codes_does_not_offer_one_by_accident(self, app):
        """
        The other half of the same mistake. A sentence naming a link --
        "The role link is a system role" would have done it -- pulled the
        form onto pages that have no short code anywhere near them.
        """
        markup = drawn(app, "FORBIDDEN", "That link is not yours to delete")

        assert LOOKUP_FORM not in markup


class TestTheHandlersPassTheRightCode:
    """
    The half the checks above cannot see.

    ``error_page`` can be perfectly right about ``LINK_NOT_FOUND`` while
    the 404 handler passes ``NOT_FOUND`` for a dead short code, and every
    check above still passes.
    """

    def test_a_dead_short_code_lands_on_a_page_with_the_form(self, client):
        response = client.get("/nosuchcode")

        assert response.status_code == 404
        assert LOOKUP_FORM in response.get_data(as_text=True)

    def test_an_address_that_is_not_a_short_code_gets_no_form(self, client):
        """
        ``/no/such/page`` cannot be a short code -- it has a slash in it --
        so it is Flask's own 404 rather than the shortener's.
        """
        response = client.get("/no/such/page")

        assert response.status_code == 404
        assert LOOKUP_FORM not in response.get_data(as_text=True)

    def test_the_script_that_drives_the_form_arrives_with_it(self, client):
        """
        The form and its script are two separate conditions in the
        template, and they were two separate copies of the same broken
        test. A form whose script did not load is a text field that
        swallows what is typed into it.
        """
        markup = client.get("/nosuchcode").get_data(as_text=True)

        assert LOOKUP_FORM in markup
        assert "js/pages/home.js" in markup
