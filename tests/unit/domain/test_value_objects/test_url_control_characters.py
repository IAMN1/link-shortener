"""
Tests that control characters cannot enter through a URL.

The check used to look at ``urlparse(...).path`` only, and two independent
things made that useless:

- ``urlsplit`` deletes ASCII tab, CR and LF from the input at any position
  before returning components, so a parsed component can never show them;
- query, params and fragment were not examined at all.

What got through: ``#\\n`` produced a link whose redirect raises for good,
because a ``Location`` header cannot hold a newline -- and since
``normalize()`` drops the fragment, it hashed identically to the clean URL
and took its place in deduplication, so the clean URL could not be shortened
into a working link any more. ``?a=\\x00`` reached PostgreSQL, which refuses
NUL in text, failing the request and, in a batch, everything alongside it.
"""

import pytest

from link_shortener.domain import OriginalUrl, ValidationError


CLEAN = "https://target.example.com/page"


class TestControlCharactersAreRefusedAnywhere:
    """Not just in the path, and not only the ones the parser leaves behind."""

    @pytest.mark.parametrize("char", ["\n", "\r", "\t"])
    @pytest.mark.parametrize(
        "template",
        [
            "https://target.example.com/page{c}",
            "https://target.example.com/page#{c}",
            "https://target.example.com/page?a={c}",
            "https://target.example.com/{c}/page",
            "https://target{c}.example.com/page",
            "{c}https://target.example.com/page",
        ],
    )
    def test_the_characters_the_parser_deletes_are_refused(self, char, template):
        with pytest.raises(ValidationError):
            OriginalUrl(template.format(c=char))

    @pytest.mark.parametrize("char", ["\x00", "\x01", "\x1f", "\x7f"])
    @pytest.mark.parametrize(
        "template",
        [
            "https://target.example.com/page?a={c}",
            "https://target.example.com/page#{c}",
            "https://target.example.com/page;{c}",
        ],
    )
    def test_the_characters_the_parser_keeps_are_refused(self, char, template):
        with pytest.raises(ValidationError):
            OriginalUrl(template.format(c=char))

    def test_an_ordinary_url_still_passes(self):
        assert OriginalUrl(CLEAN).value == CLEAN

    def test_percent_encoded_control_characters_are_fine(self):
        """Encoded, they are just characters in a string and never a header."""
        assert OriginalUrl(f"{CLEAN}?a=%0A").value.endswith("%0A")


class TestAPoisonedUrlCannotStealACleanOnesIdentity:
    """
    The fragment is dropped by normalisation, so ``#\\n`` hashed the same as
    the clean URL -- and deduplication then handed everyone the broken one.
    """

    def test_the_poisoned_form_never_gets_stored_to_begin_with(self):
        with pytest.raises(ValidationError):
            OriginalUrl(f"{CLEAN}#\n")

    def test_the_clean_form_is_unaffected(self):
        assert OriginalUrl(CLEAN).normalize() == OriginalUrl(CLEAN).normalize()


class TestStoredRowsStayReadable:
    """
    The ban is an admission rule, so it does not apply on the way out.

    Rows written before it existed have to remain readable, or one of them
    fails every maintenance sweep -- which is exactly what would stop them
    being cleaned up.
    """

    def test_a_row_written_before_the_ban_can_still_be_read(self):
        stored = OriginalUrl.from_storage(f"{CLEAN}#\n")

        assert stored.value == f"{CLEAN}#\n"

    def test_a_row_with_a_scheme_since_disallowed_can_still_be_read(self):
        stored = OriginalUrl.from_storage("ftp://files.example.com/a.tar")

        assert stored.value == "ftp://files.example.com/a.tar"

    def test_reading_still_refuses_something_that_is_not_a_url(self):
        with pytest.raises(ValidationError):
            OriginalUrl.from_storage("nonsense")
