"""
The sentences the service itself writes, in the language of the request.

``tests/unit/web/test_translations.py`` says the catalogues are complete
and current; ``test_pages_come_out_in_the_chosen_language.py`` says the
words on a page change. Neither sees this one: a refusal's ``message`` is
not written in a template, it is written in the domain and translated at
the boundary, and every part of that route can break while both of those
stay green.

The routes it can break on:

  - the sentence never marked, so it is in no catalogue;
  - marked but built by an f-string, so the finished text is not a msgid
    and ``gettext`` hands it straight back;
  - translated for the page and not for the API, or the other way round;
  - a value lost on the way, so "Link with code (abc) not found" comes out
    with an empty pair of brackets.

Read back off a real response for the same reason the page tests are:
asking Babel what Babel says would pass against an empty catalogue.
"""

import pytest

from link_shortener.domain.exceptions import (
    DomainError, LinkNotFoundError, PermissionsNotFoundError,
    RoleAlreadyExistsError, RoleIsSystemError, RoleNotFoundError
)
from link_shortener.web.i18n import translate_error


DEAD_CODE = "nosuchcode"
"""A short code nothing was ever created for."""


def in_language(app, language):
    """
    A client that has chosen a language.

    Set through the cookie jar rather than as a ``Cookie`` header: the
    test client keeps its own jar and drops a header handed to it, which
    leaves the server seeing an anonymous, language-less request and every
    assertion below passing against English.

    Args:
        app: The application under test.
        language: Language tag to choose.

    Returns:
        A test client carrying that choice.
    """
    client = app.test_client()
    client.set_cookie("lang", language, domain="localhost")
    return client


class TestARefusalIsWrittenInTheReadersLanguage:

    @pytest.mark.parametrize("language,expected", [
        ("en", "Link not found"),
        ("ru", "Ссылка не найдена"),
        ("zh", "找不到该链接"),
    ])
    def test_the_error_page_says_it_in_the_chosen_language(
        self, app, language, expected
    ):
        markup = in_language(app, language).get(f"/{DEAD_CODE}").get_data(as_text=True)

        assert expected in markup

    @pytest.mark.parametrize("language,expected", [
        ("en", "Link with code (nosuchcode) not found"),
        ("ru", "Ссылка с кодом (nosuchcode) не найдена"),
        ("zh", "找不到代码为 (nosuchcode) 的链接"),
    ])
    def test_the_api_says_it_in_the_chosen_language(
        self, app, language, expected
    ):
        """
        The API answers by the same cookie, which is the decision this
        project took: a browser sends it to its own ``/api/`` calls, and a
        programmatic client carries no cookie and gets English.
        """
        body = in_language(app, language).get(
            f"/api/v1/links/{DEAD_CODE}"
        ).get_json()

        assert body["message"] == expected

    def test_a_client_that_carries_no_cookie_is_answered_in_english(self, app):
        """
        The other half of that decision. A program with no cookie jar is
        not a reader with a preference, and English is the language the
        API's own document is written in.
        """
        body = app.test_client().get(f"/api/v1/links/{DEAD_CODE}").get_json()

        assert body["message"] == "Link with code (nosuchcode) not found"

    def test_the_value_inside_the_sentence_survives_translation(self, app):
        """
        The failure a marked-but-f-string sentence gives: the catalogue
        entry is found, and the code it was about is not in it.
        """
        body = in_language(app, "ru").get(
            f"/api/v1/links/{DEAD_CODE}"
        ).get_json()

        assert DEAD_CODE in body["message"]


class TestTranslatingAtTheBoundary:
    """
    ``translate_error`` on its own, including the ways a catalogue can be
    wrong. A catalogue is a file an operator edits, so it is input.
    """

    def test_a_sentence_with_no_values_is_looked_up_whole(self, app):
        with app.test_request_context("/", headers={"Cookie": "lang=ru"}):
            assert translate_error(LinkNotFoundError()) == "Ссылка не найдена"

    def test_a_template_gets_its_values_put_back(self, app):
        with app.test_request_context("/", headers={"Cookie": "lang=ru"}):
            said = translate_error(LinkNotFoundError("abc123"))

        assert said == "Ссылка с кодом (abc123) не найдена"

    def test_a_translation_naming_a_placeholder_that_is_not_there_falls_back(
        self, app
    ):
        """
        The failure mode that must not be a crash: this runs inside the
        error handler, so raising here answers a missing page with a 500 --
        and the 500 handler calls the same code again.
        """
        broken = DomainError(
            "Link with code (abc) not found",
            "LINK_NOT_FOUND",
            template="Link with code (%(short_code)s) not found",
            params={"code": "abc"},
        )

        with app.test_request_context("/", headers={"Cookie": "lang=ru"}):
            assert translate_error(broken) == "Link with code (abc) not found"

    def test_an_unmarked_sentence_comes_back_as_it_was_written(self, app):
        """
        Nothing in the catalogue matches, and ``gettext`` answers the
        msgid. English, which is the honest answer -- not a crash and not
        an empty string.
        """
        unmarked = DomainError("Something nobody ever marked", "DOMAIN_ERROR")

        with app.test_request_context("/", headers={"Cookie": "lang=ru"}):
            assert translate_error(unmarked) == "Something nobody ever marked"


class TestWhatTheLogsKeep:

    def test_the_exception_still_carries_the_english_sentence(self):
        """
        Translation happens at the boundary and nowhere else. If it
        happened where the error is raised, ``application.log`` would fill
        with Russian for an operator who did not choose it -- and the same
        failure would be two different strings depending on who tripped
        over it.
        """
        error = LinkNotFoundError("abc123")

        assert error.message == "Link with code (abc123) not found"
        assert error.template == "Link with code (%(code)s) not found"
        assert error.params == {"code": "abc123"}


class TestTheRoleRefusalsAreMarkedToo:
    """
    The refusals that reached the reader in English until the service
    stopped raising bare ``ValueError`` for them -- and one more beside
    them: "Registration is unavailable" is answered 400 by
    ``AuthController.register``, which words every ``DomainError`` on that
    route itself rather than by the status table, so it is read by whoever
    tried to register rather than by an operator reading a 5xx.

    A bare exception carries a finished f-string and nothing to look a
    sentence up by, so the boundary had no template to translate and the
    envelope said "Role 'x' already exists" to a page rendered in Russian.
    These pin the three sentences that replaced it, one per catalogue
    entry: an empty ``msgstr``, a ``fuzzy`` flag or a lost placeholder each
    turn one of them red.
    """

    @pytest.mark.parametrize("error,expected", [
        (
            DomainError(
                "Registration is unavailable", "CONFIGURATION_ERROR"
            ),
            "Регистрация сейчас недоступна",
        ),
        (RoleAlreadyExistsError("editor"), "Роль editor уже существует"),
        (RoleNotFoundError("editor"), "Роль editor не найдена"),
        (
            RoleIsSystemError("admin"),
            "Роль admin принадлежит службе: её нельзя ни изменить, ни удалить",
        ),
        (
            PermissionsNotFoundError({"link:fly"}),
            "Права не найдены: link:fly",
        ),
    ])
    def test_each_role_refusal_is_in_the_catalogue(self, app, error, expected):
        with app.test_request_context("/", headers={"Cookie": "lang=ru"}):
            assert translate_error(error) == expected

    def test_the_name_survives_the_translation(self, app):
        """The half a marked-but-f-string sentence loses."""
        with app.test_request_context("/", headers={"Cookie": "lang=zh"}):
            assert "editor" in translate_error(RoleAlreadyExistsError("editor"))


class TestABatchRefusesInTheReadersLanguage:
    """
    The per-item refusals of a batch, which are the ones that got away.

    A batch answers 200 with a verdict per item, so its refusals are not
    raised and never pass the error handler -- the one place that words a
    refusal in the reader's language. Written as finished sentences inside
    the use case, they reached a Russian reader in English while the
    single-link route, refusing the same URL for the same reason, answered
    in Russian.

    Read off a real response, like the tests above: asking the catalogue
    what the catalogue says would pass against a use case that never
    consults it.
    """

    BAD_URL = "ftp://batch-language.example.com"
    """Refused by the value object, for its scheme, and costing no quota:
    a refused item is never created, so this can be asked in any language
    without spending the guest allowance the address is counted under."""

    @pytest.mark.parametrize("language,expected", [
        ("ru", "Схема «ftp» не разрешена. Разрешённые схемы: http, https"),
        ("zh", "不允许使用协议「ftp」。允许的协议：http, https"),
        ("en", "Scheme 'ftp' is not allowed. Allowed schemes: http, https"),
    ])
    def test_a_refused_item_says_it_in_the_chosen_language(
        self, app, language, expected
    ):
        response = in_language(app, language).post(
            "/api/v1/batch/shorten", json={"urls": [self.BAD_URL]}
        )

        body = response.get_json()
        assert response.status_code == 200, body
        assert body["results"][0]["error"] == expected

    def test_the_same_refusal_reads_the_same_on_both_routes(self, app):
        """The property that was broken, stated as one comparison.

        One URL, one reason, two endpoints: whatever the single-link route
        says, the batch says. This is what a per-item sentence written in
        the application layer cannot hold, however carefully it is worded.
        """
        client = in_language(app, "ru")

        single = client.post("/api/v1/shorten", json={"url": self.BAD_URL})
        batch = client.post(
            "/api/v1/batch/shorten", json={"urls": [self.BAD_URL]}
        )

        assert (
            batch.get_json()["results"][0]["error"]
            == single.get_json()["message"]
        )
