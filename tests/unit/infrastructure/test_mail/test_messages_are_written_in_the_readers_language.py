"""
Confirmation messages, in the language the person was reading.

A message is rendered in a Celery worker, where there is no request at
all: ``select_language`` there honestly answers the configured default,
so the language cannot be negotiated at send time. It has to travel with
the work -- ``RequestContext.language``, set where a request exists --
and this file is what says that route still holds end to end.

Rendered through its own Jinja environment, not Flask's, which is the
part most easily got wrong: a plain environment has no ``{% trans %}`` at
all, and a template carrying the tag raises ``TemplateSyntaxError`` at
send time, inside a worker, on a registration that already committed.
"""

import pytest

from link_shortener.infrastructure.mail.jinja_templates import JinjaMailTemplates


@pytest.fixture
def templates():
    """The real renderer, reading the real catalogues."""
    return JinjaMailTemplates()


class TestTheConfirmationMessage:

    def test_english_is_what_a_message_with_no_language_gets(self, templates):
        """
        ``None`` is what a task queued before this field existed carries,
        and what the CLI has. It must render, not fail.
        """
        subject, body = templates.verification_email("https://x/y", 24, None)

        assert subject == "Confirm your email address"
        assert "Open this link to confirm the address" in body

    @pytest.mark.parametrize("language,expected_subject", [
        ("en", "Confirm your email address"),
        ("ru", "Подтвердите адрес почты"),
        ("zh", "确认您的邮箱地址"),
    ])
    def test_the_subject_follows_the_chosen_language(
        self, templates, language, expected_subject
    ):
        subject, _body = templates.verification_email("https://x/y", 24, language)

        assert subject == expected_subject

    def test_the_link_itself_is_never_translated(self, templates):
        """
        The one thing in the message that must survive every catalogue.
        """
        _subject, body = templates.verification_email(
            "https://example.com/verify?token=abc", 24, "ru"
        )

        assert "https://example.com/verify?token=abc" in body

    @pytest.mark.parametrize("hours,ending", [
        (1, "1 час."),
        (24, "24 часа."),
        (5, "5 часов."),
    ])
    def test_russian_takes_the_form_the_count_calls_for(
        self, templates, hours, ending
    ):
        """
        Why the template uses ``{% trans %}``/``{% pluralize %}`` rather
        than the ``{{ 's' if ttl_hours != 1 }}`` it carried before. That
        trick has exactly two outcomes and Russian needs three, chosen by
        arithmetic on the last two digits: 24 takes the second form and 5
        the third, and neither is reachable by an ``if n != 1``.

        All three are listed because the service ships with 24 -- the one
        a single-form catalogue would get wrong without anybody noticing.
        """
        _subject, body = templates.verification_email("https://x/y", hours, "ru")

        assert ending in body

    def test_a_language_with_no_catalogue_still_sends(self, templates):
        """
        A deployment offering a language nobody compiled must not stop
        sending mail over it. English is a poor answer and a far better
        one than a message that never goes out.
        """
        subject, body = templates.verification_email("https://x/y", 24, "xx")

        assert subject == "Confirm your email address"
        assert body.strip()


class TestTheAddressAlreadyRegisteredMessage:

    @pytest.mark.parametrize("language,expected_subject", [
        ("en", "Someone tried to register your address"),
        ("ru", "Кто-то попытался зарегистрировать ваш адрес"),
        ("zh", "有人尝试注册您的地址"),
    ])
    def test_the_subject_follows_the_chosen_language(
        self, templates, language, expected_subject
    ):
        subject, _body = templates.account_exists_email("https://x/login", language)

        assert subject == expected_subject

    def test_the_sign_in_link_survives(self, templates):
        _subject, body = templates.account_exists_email("https://x/login", "zh")

        assert "https://x/login" in body


class TestOneWorkerServesEveryLanguage:

    def test_a_second_message_is_not_answered_in_the_first_ones_language(
        self, templates
    ):
        """
        The failure a catalogue installed once, in the constructor, would
        give: a worker process sends to everybody, and whichever language
        arrived first would answer for the rest of the process's life.
        The renderer is reused here on purpose -- a fresh one per call
        would hide exactly that.
        """
        russian, _ = templates.verification_email("https://x/y", 24, "ru")
        chinese, _ = templates.verification_email("https://x/y", 24, "zh")
        english, _ = templates.verification_email("https://x/y", 24, "en")

        assert russian == "Подтвердите адрес почты"
        assert chinese == "确认您的邮箱地址"
        assert english == "Confirm your email address"
