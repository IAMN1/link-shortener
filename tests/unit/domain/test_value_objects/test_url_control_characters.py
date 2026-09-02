"""
Tests that control characters cannot enter through a URL.

Looking at ``urlparse(...).path`` only is useless for two independent
reasons:

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

    @pytest.mark.parametrize(
        "char, name",
        [(" ", "space, the first character above the C0 block"),
         ("~", "tilde, the last one below DEL"),
         ("\x80", "the first character above DEL")],
    )
    def test_the_characters_just_outside_the_ban_are_admitted(self, char, name):
        """The ban is C0 and DEL, and the three characters that touch its
        edges are not in it.

        Only these tell ``< 32`` from ``<= 32`` and ``== 127`` from
        ``!= 127``: a comparison off by one refuses a URL a browser opens
        and every refusal test in this class stays green, because refusing
        more is what they ask for.
        """
        url = f"{CLEAN}/page{char}"

        assert OriginalUrl(url).value == url

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
        assert OriginalUrl(CLEAN).normalize() == CLEAN


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


class TestThePathIsCheckedAgainAfterParsing:
    """
    A second guard over the same characters, in the parsed path.

    Nothing reaches it through the constructor: the whole-string check
    runs first and refuses every C0 character wherever it sits. It is not
    dead -- it is what stands if the first check is ever narrowed, and the
    two are in different methods with nothing but their order between
    them. Asked of the validator directly, which is the only caller that
    can get to it.
    """

    def test_a_control_character_in_the_parsed_path_is_refused(self):
        from urllib.parse import urlparse

        parsed = urlparse("https://target.example.com/pa\x01ge")

        with pytest.raises(ValidationError, match="Path contains control"):
            OriginalUrl.from_storage(CLEAN)._validate_path(parsed)

    def test_an_ordinary_path_passes_it(self):
        from urllib.parse import urlparse

        parsed = urlparse(CLEAN)

        OriginalUrl.from_storage(CLEAN)._validate_path(parsed)

    def test_the_constructor_refuses_such_a_url_earlier(self):
        """Stated so the guard above is not read as the answer a caller
        gets: the message names the whole URL, not the path."""
        with pytest.raises(ValidationError, match="URL contains control"):
            OriginalUrl("https://target.example.com/pa\x01ge")
