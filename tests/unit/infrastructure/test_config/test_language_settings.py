"""What a deployment is allowed to say about the interface language.

Both faults here are silent at runtime rather than loud, which is why they
are checked at startup instead. A ``SUPPORTED_LANGUAGES`` nobody filled in
leaves the negotiator with nothing to match and every page falls through to
the default; a ``DEFAULT_LANGUAGE`` outside the list makes that fall-through
land on a language the deployment does not offer. Neither raises anywhere,
nothing is logged, and the pages come out looking fine -- in the wrong
language.

Built from the environment rather than from pinned class attributes: a
pinned setting shadows the descriptor that implements it, and the code under
test then never runs.
"""

import pytest

from link_shortener.infrastructure.configs.app.development import (
    DevelopmentConfig
)


pytestmark = pytest.mark.usefixtures("detached_env")


def configure(monkeypatch, **overrides):
    """
    Write the language settings into the environment.

    Args:
        monkeypatch: pytest's environment patcher.
        **overrides: Settings to place, by their environment names.

    Returns:
        A configuration built from that environment.
    """
    for name, value in overrides.items():
        monkeypatch.setenv(name, value)

    return DevelopmentConfig()


def refusal(config):
    """
    Run validation and hand back what it objected to.

    Args:
        config: The configuration to validate.

    Returns:
        The refusal text, or None when the configuration was accepted.
    """
    try:
        config.validate()
    except ValueError as error:
        return str(error)

    return None


class TestTheDefaultHasToBeOnOffer:

    def test_a_default_outside_the_list_is_refused(self, monkeypatch):
        config = configure(
            monkeypatch,
            SUPPORTED_LANGUAGES="en,ru",
            DEFAULT_LANGUAGE="zh",
        )

        assert "DEFAULT_LANGUAGE" in (refusal(config) or "")

    def test_the_refusal_names_both_sides(self, monkeypatch):
        """
        A message that says only "invalid" sends the reader back to the
        documentation. This one has to carry the value that was refused and
        the values that would have been accepted, because that is the whole
        of what the operator needs to fix it.
        """
        config = configure(
            monkeypatch,
            SUPPORTED_LANGUAGES="en,ru",
            DEFAULT_LANGUAGE="zh",
        )

        said = refusal(config) or ""

        assert "zh" in said
        assert "en, ru" in said

    def test_a_default_that_is_on_offer_is_accepted(self, monkeypatch):
        config = configure(
            monkeypatch,
            SUPPORTED_LANGUAGES="en,ru",
            DEFAULT_LANGUAGE="ru",
        )

        assert refusal(config) is None

    def test_case_alone_is_not_a_refusal(self, monkeypatch):
        """
        Language tags are case-insensitive by RFC 5646. Refusing to start
        over ``DEFAULT_LANGUAGE=EN`` would be pedantry, and it is the kind
        of pedantry that gets a validation step deleted.
        """
        config = configure(
            monkeypatch,
            SUPPORTED_LANGUAGES="en,ru",
            DEFAULT_LANGUAGE="EN",
        )

        assert refusal(config) is None


class TestSomethingHasToBeOnOffer:

    def test_a_blank_value_falls_back_to_the_default(self, monkeypatch):
        """
        Blank means unset here, service-wide: ``docker compose``
        substitutes an empty string for every ``${VAR}`` its env file does
        not carry, so a blank has to behave like an absent variable rather
        than like a deliberate empty setting. Pinned because the obvious
        reading of the check above -- "empty is refused" -- would be wrong,
        and a reader who acted on it would make an unconfigured compose
        stack refuse to start.
        """
        config = configure(monkeypatch, SUPPORTED_LANGUAGES="")

        assert refusal(config) is None
        assert config.SUPPORTED_LANGUAGES == ["en", "ru", "zh"]

    def test_a_list_of_nothing_but_separators_is_refused(self, monkeypatch):
        """
        ``SUPPORTED_LANGUAGES=" , , "`` is not blank, so it is a deliberate
        setting -- and it names no language at all. This is the shape an
        empty list can really arrive in, and the check has to survive the
        stripping rather than run before it.
        """
        config = configure(monkeypatch, SUPPORTED_LANGUAGES=" , , ")

        assert "SUPPORTED_LANGUAGES" in (refusal(config) or "")


class TestATagTheCatalogueMachineryCanCarry:
    """
    A language the deployment names has to be one Babel can parse.

    The other two checks in this file catch faults that are silent -- the
    page comes out in the wrong language and nobody files a bug. This one
    is the opposite, which is why it exists: ``select_language`` hands the
    negotiated tag to Flask-Babel, which parses it with ``_`` as the
    separator, so ``SUPPORTED_LANGUAGES=en,pt-BR`` starts cleanly and then
    answers **500** to the first browser that asks for Portuguese -- every
    page, and the error handler with them, since that renders a page too.
    """

    @pytest.mark.parametrize("tag", ["pt-BR", "zh-Hans", "klingon", "xx"])
    def test_a_tag_babel_cannot_read_is_refused_at_startup(
        self, monkeypatch, tag
    ):
        config = configure(monkeypatch, SUPPORTED_LANGUAGES=f"en,{tag}")

        assert "SUPPORTED_LANGUAGES" in (refusal(config) or "")

    @pytest.mark.parametrize("tag", ["pt_BR", "zh_Hans", "de", "fr"])
    def test_a_tag_it_can_read_is_accepted(self, monkeypatch, tag):
        """The other half: the check must not refuse a language somebody
        could legitimately add."""
        config = configure(
            monkeypatch, SUPPORTED_LANGUAGES=f"en,{tag}", DEFAULT_LANGUAGE="en"
        )

        assert refusal(config) is None

    def test_the_refusal_names_the_spelling_that_works(self, monkeypatch):
        """An operator reading this has to know what to write instead, not
        merely that something was wrong."""
        config = configure(monkeypatch, SUPPORTED_LANGUAGES="en,pt-BR")

        assert "pt_BR" in (refusal(config) or "")

    def test_babel_really_does_refuse_what_this_refuses(self):
        """The premise. Without it the list above is four strings this
        file agrees with itself about."""
        from babel import Locale

        with pytest.raises(Exception):
            Locale.parse("pt-br")

        assert str(Locale.parse("pt_BR")) == "pt_BR"


class TestTheDefaults:

    def test_the_three_languages_are_offered_out_of_the_box(self, monkeypatch):
        config = DevelopmentConfig()

        assert config.SUPPORTED_LANGUAGES == ["en", "ru", "zh"]

    def test_english_is_the_language_of_a_caller_who_asked_for_none(self):
        """
        Which is most callers of the API and, measured, every request the
        test suite and the browser run make: neither declares a language at
        all. This is not an edge case -- it is what a program sees.
        """
        config = DevelopmentConfig()

        assert config.DEFAULT_LANGUAGE == "en"
