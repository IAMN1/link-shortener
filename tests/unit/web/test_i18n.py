"""
Which language a request is answered in.

The order under test is cookie, then ``Accept-Language``, then the
configured default -- and each step is here because skipping it produces a
page that renders, returns 200 and is in the wrong language. Nothing raises
and nothing is logged, so only a test that reads the answer can catch it.

The last case in each class is the one that matters most in practice: a
value the service never wrote. A cookie is client-side, so its content is
whatever anyone typed, and a language tag that is no longer offered is the
ordinary state of a visitor after ``SUPPORTED_LANGUAGES`` is narrowed.

The cookie is put on the request through ``test_request_context`` and a
``Cookie`` header, which works. Measured, because the obvious alternative
does not: a ``Cookie`` header handed to ``test_client`` is **dropped** --
the client keeps a cookie jar of its own and answers from that, so the
server sees no cookies at all. A test written that way passes while
exercising the branch for a visitor who sent nothing, which is the branch
that answers English no matter what the header said. On a test client, use
``set_cookie``.
"""

from link_shortener.web.i18n import (
    LANGUAGE_COOKIE_NAME,
    default_language,
    language_from_cookie,
    select_language,
    supported_languages,
)


def chosen(app, cookie=None, accept=None):
    """
    Ask the selector what this request would be answered in.

    Args:
        app: Application whose configuration is in force.
        cookie: Value of the language cookie, or None to send none.
        accept: ``Accept-Language`` header value, or None to send none.

    Returns:
        The language tag the selector picked.
    """
    headers = {}
    if cookie is not None:
        headers["Cookie"] = f"{LANGUAGE_COOKIE_NAME}={cookie}"
    if accept is not None:
        headers["Accept-Language"] = accept

    with app.test_request_context("/", headers=headers):
        return select_language()


class TestNothingWasAskedFor:

    def test_a_caller_who_declares_nothing_gets_the_default(self, app):
        """
        Measured, and not an edge case: neither the Flask test client nor
        the Chromium the browser run drives sends ``Accept-Language`` at
        all. This branch is what the whole suite and both live runs take.
        """
        assert chosen(app) == "en"

    def test_a_header_that_cannot_be_parsed_falls_back(self, app):
        assert chosen(app, accept="не заголовок вовсе") == "en"

    def test_an_empty_header_falls_back(self, app):
        assert chosen(app, accept="") == "en"


class TestTheBrowsersOwnPreference:

    def test_a_language_on_offer_is_honoured(self, app):
        assert chosen(app, accept="ru") == "ru"

    def test_a_region_matches_the_bare_tag(self, app):
        """
        What a real browser sends is ``ru-RU``, never a bare ``ru``. The
        matching is Werkzeug's rather than ours, and this holds it: a
        selector that compared strings would answer English to every
        Russian browser on earth.
        """
        assert chosen(app, accept="ru-RU") == "ru"

    def test_a_full_browser_header_picks_the_first_language_on_offer(self, app):
        assert chosen(app, accept="ru-RU,ru;q=0.9,en;q=0.8") == "ru"

    def test_a_language_not_on_offer_falls_back(self, app):
        assert chosen(app, accept="fr-FR,fr;q=0.9") == "en"


class TestADeliberateChoiceOutranksTheBrowser:

    def test_the_cookie_wins_over_the_header(self, app):
        """
        The header is what the browser was installed with; the cookie is
        what the visitor pressed. A visitor who picked Russian on an
        English-configured machine has said something the installer did
        not.
        """
        assert chosen(app, cookie="ru", accept="en-US,en;q=0.9") == "ru"

    def test_the_cookie_wins_the_other_way_round_too(self, app):
        assert chosen(app, cookie="en", accept="ru-RU,ru;q=0.9") == "en"

    def test_a_language_that_is_no_longer_offered_is_ignored(self, app):
        """
        Ignored, not refused. Answering 400 to a stale cookie would lock a
        visitor out of every page with no way back that does not involve
        clearing cookies by hand.
        """
        assert chosen(app, cookie="xx", accept="ru-RU") == "ru"

    def test_an_ignored_cookie_still_reaches_the_default(self, app):
        assert chosen(app, cookie="xx") == "en"

    def test_a_cookie_of_rubbish_does_not_raise(self, app):
        assert chosen(app, cookie="<script>alert(1)</script>") == "en"

    def test_case_does_not_matter(self, app):
        """Language tags are case-insensitive by RFC 5646."""
        assert chosen(app, cookie="RU") == "ru"

    def test_surrounding_space_does_not_matter(self, app):
        assert chosen(app, cookie=" ru ") == "ru"


class TestTheHelpersReadTheConfiguration:

    def test_the_offered_languages_come_from_the_configuration(self, app):
        with app.test_request_context("/"):
            assert supported_languages() == ["en", "ru", "zh"]

    def test_empty_entries_are_dropped(self, app):
        """
        ``SUPPORTED_LANGUAGES=en,,ru`` is a typo. Left in, the empty string
        becomes a language nobody can select and every comparison against
        it silently succeeds.
        """
        app.config["SUPPORTED_LANGUAGES"] = ["en", "", "  ", "ru"]

        with app.test_request_context("/"):
            assert supported_languages() == ["en", "ru"]

    def test_the_default_is_normalised(self, app):
        app.config["DEFAULT_LANGUAGE"] = " RU "

        with app.test_request_context("/"):
            assert default_language() == "ru"

    def test_the_cookie_reader_answers_none_when_none_was_sent(self, app):
        with app.test_request_context("/"):
            assert language_from_cookie() is None


class TestOutsideARequest:

    def test_the_default_is_answered_rather_than_raising(self, app):
        """
        The mail worker renders templates with no request anywhere near it
        -- it runs in Celery, where the request that caused the mail is
        long finished. Raising there would turn "send a confirmation
        message" into a failed task.
        """
        with app.app_context():
            assert select_language() == "en"


class TestTheChoiceIsHandedToTheTemplates:

    def test_the_layout_is_given_the_language_that_was_chosen(self, app):
        """
        The context processor and the catalogue must be fed by the same
        function, or the page says it is in one language and is written in
        another.
        """
        with app.test_request_context("/", headers={"Accept-Language": "ru-RU"}):
            context = app.jinja_env.globals.copy()
            for processor in app.template_context_processors[None]:
                context.update(processor())

        assert context["current_language"] == "ru"
