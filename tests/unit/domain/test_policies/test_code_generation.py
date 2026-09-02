"""
How a URL becomes a code, and what changes it.

Every use case that generates a code does it through a ``Mock``, so the
policy itself was reached only sideways -- through the integration tests
that happen to create links. What went unheld is the arithmetic of the
attempt counter: the first attempt is the URL's own code and every later
one is salted, and flipping that comparison left the whole suite green.

Driven with the real ``Base64UrlCodeGenerator``, because the base class
is an interface: the two methods under test are the ones it implements
for every generator, and they are only meaningful over a real ``generate``.
"""

import pytest

from link_shortener.domain.value_objects.original_url import OriginalUrl
from link_shortener.infrastructure.policies.base64_url_code_generator import (
    Base64UrlCodeGenerator,
)


URL = OriginalUrl("https://example.com/a-page")


@pytest.fixture
def generator():
    """A generator of the shape the container builds."""
    return Base64UrlCodeGenerator(
        code_length=6, min_length=4, max_length=10, pepper="test-pepper",
    )


class TestTheFirstAttemptIsTheUrlsOwnCode:
    """Attempt 0 means "no salt", and it is the code deduplication finds."""

    def test_the_first_attempt_is_the_plain_code(self, generator):
        assert generator.generate_unique(URL, attempt=0) == (
            generator.generate(URL.normalize())
        )

    def test_it_is_what_generate_for_url_answers_too(self, generator):
        assert generator.generate_for_url(URL) == (
            generator.generate_unique(URL, attempt=0)
        )

    def test_a_later_attempt_is_a_different_code(self, generator):
        """The point of the counter: the first code was taken."""
        assert generator.generate_unique(URL, attempt=1) != (
            generator.generate_unique(URL, attempt=0)
        )

    def test_every_attempt_answers_a_code_of_its_own(self, generator):
        codes = {
            generator.generate_unique(URL, attempt=attempt).value
            for attempt in range(5)
        }

        assert len(codes) == 5, codes

    def test_the_same_attempt_always_answers_the_same_code(self, generator):
        """Deterministic, which is what makes a retry find the same row
        rather than making a second one."""
        assert generator.generate_unique(URL, attempt=3) == (
            generator.generate_unique(URL, attempt=3)
        )


class TestTwoUrlsDoNotShareACode:

    def test_a_different_url_gets_a_different_code(self, generator):
        other = OriginalUrl("https://example.com/another-page")

        assert generator.generate_for_url(URL) != generator.generate_for_url(other)

    def test_two_spellings_of_one_url_get_one_code(self, generator):
        """The code is taken from the normalised form, which is what makes
        deduplication see the two spellings as one link."""
        assert generator.generate_for_url(OriginalUrl("HTTPS://EXAMPLE.com/a-page")) \
            == generator.generate_for_url(URL)


class TestACodeWithNoCeilingBehindIt:
    """``generate_fresh`` exists because the attempts run out."""

    def test_two_fresh_codes_for_one_url_differ(self, generator):
        assert generator.generate_fresh(URL) != generator.generate_fresh(URL)

    def test_a_fresh_code_is_none_of_the_deterministic_ones(self, generator):
        deterministic = {
            generator.generate_unique(URL, attempt=attempt).value
            for attempt in range(5)
        }

        assert generator.generate_fresh(URL).value not in deterministic

    def test_a_fresh_code_is_still_a_usable_code(self, generator):
        """It goes through ``ShortCode``, so it is bounded and spellable --
        a nonce in the input must not reach the code itself."""
        code = generator.generate_fresh(URL).value

        assert len(code) == 6
        assert code.isascii()
