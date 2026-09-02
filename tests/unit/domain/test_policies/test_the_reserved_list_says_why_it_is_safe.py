"""
The sentence at the top of ``reserved_codes.py``, held against the facts.

That docstring explains why a reserved word is only a custom code's
problem. It used to give the reason as "generated codes are random and
the chance is negligible". They are not random: a code is
``sha256(url + pepper)`` cut to ``SHORT_CODE_LENGTH`` Base64URL
characters -- the same URL gives the same code on every call, which is
what deduplication is built on. The conclusion survived the correction;
the reason did not, and nothing was holding it.

What is held here is the arithmetic the corrected sentence rests on: how
many reserved names could collide with a generated code at the shipped
length, and that a code is derived from its inputs rather than drawn.
Both are facts a later edit can quietly move -- a reserved word added, a
length changed -- and each would leave the sentence saying a number that
is no longer true.
"""

import re

from link_shortener.domain.policies import reserved_codes
from link_shortener.domain.policies.reserved_codes import RESERVED_CODES
from link_shortener.domain.value_objects.original_url import OriginalUrl
from link_shortener.infrastructure.configs.app.base import BaseConfig
from link_shortener.infrastructure.policies.base64_url_code_generator import (
    Base64UrlCodeGenerator,
)


NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
"""Small numbers as the docstring writes them, which is in words."""

CLAIMED_COLLIDABLE = re.compile(
    r"landing on one of the\s+(\w+) reserved names of that same length"
)
"""How many reserved names the docstring says share the shipped length."""


def claimed_count() -> int:
    """
    The count the docstring names, read out of the docstring.

    Returns:
        The number of same-length reserved names the sentence claims.

    Raises:
        AssertionError: If the sentence is no longer there. A rewrite is
            the moment to point this at the new wording, not to stop
            checking.
    """
    found = CLAIMED_COLLIDABLE.search(reserved_codes.__doc__ or "")
    assert found, (
        "reserved_codes.py no longer states how many reserved names share "
        "the generated length; the sentence this test reads has changed"
    )
    word = found.group(1)
    return NUMBER_WORDS.get(word, -1)


class TestTheCountInTheSentence:

    def test_the_sentence_is_still_there_to_read(self):
        assert claimed_count() > 0

    def test_it_matches_the_shipped_list_and_length(self):
        """
        The names that could actually collide, counted from the list.

        A generated code is exactly ``SHORT_CODE_LENGTH`` characters, so
        only reserved names of that length can ever be produced. Shorter
        and longer ones are out of reach whatever the hash says.
        """
        same_length = [
            code for code in RESERVED_CODES
            if len(code) == BaseConfig.SHORT_CODE_LENGTH
        ]

        assert len(same_length) == claimed_count()


class TestACodeIsDerivedRatherThanDrawn:
    """The half of the sentence that replaced the word "random"."""

    URL = OriginalUrl("https://example.com/derived-not-drawn")

    def _generator(self, pepper: str) -> Base64UrlCodeGenerator:
        return Base64UrlCodeGenerator(
            code_length=BaseConfig.SHORT_CODE_LENGTH,
            min_length=4,
            max_length=10,
            pepper=pepper,
        )

    def test_two_generators_with_one_pepper_agree(self):
        """
        Not random: the code is a function of the URL and the pepper.

        Two generators that never met answer the same code for the same
        URL, which no drawn value would do.
        """
        first = self._generator("one-pepper").generate(self.URL.value)
        second = self._generator("one-pepper").generate(self.URL.value)

        assert first.value == second.value

    def test_a_different_pepper_gives_a_different_code(self):
        """The pepper is in the hash, which is why it is a secret."""
        here = self._generator("one-pepper").generate(self.URL.value)
        there = self._generator("another-pepper").generate(self.URL.value)

        assert here.value != there.value

    def test_the_code_is_the_length_the_arithmetic_assumes(self):
        """64**7 is only the right number while the code is seven long."""
        code = self._generator("one-pepper").generate(self.URL.value)

        assert len(code.value) == BaseConfig.SHORT_CODE_LENGTH
