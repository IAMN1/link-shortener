"""
Tests for what the service will accept as a password.

The policy bounds the minimum length as well as the maximum. Bounding
only the maximum -- which exists to keep a password inside what bcrypt can
hash -- lets registration accept ``short``.

The rules follow NIST SP 800-63B: a length floor and a check against
passwords attackers already have, and deliberately no composition rules --
"must contain a digit and a symbol" produces ``Password1!``, which is early
in every cracking list, while refusing a long passphrase, which is not.
"""

import pytest

from link_shortener.domain.exceptions import ValidationError
from link_shortener.domain.policies.password_policy import (
    MAX_PASSWORD_BYTES, MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH,
    validate_password
)


class TestTooShort:

    @pytest.mark.parametrize("password", ["a", "short", "1234567"])
    def test_it_is_refused(self, password):
        with pytest.raises(ValidationError, match="at least"):
            validate_password(password)

    def test_an_empty_password_is_refused_as_blank(self):
        """It is refused either way; the reason moved.

        An empty string is now caught by the blank check, which runs
        first, so the message says so rather than talking about a length
        the password does not have.
        """
        with pytest.raises(ValidationError, match="blank"):
            validate_password("")

    def test_the_shortest_allowed_length_passes(self):
        validate_password("h" * MIN_PASSWORD_LENGTH)


class TestBlank:
    """Whitespace is length without content, and length was the only bar.

    Through ``flask create-admin``, which prompts with the input hidden:
    eight spaces clear the floor, clear the ceiling, and are on no
    common-password list, so the most privileged account in
    the service was created with a password nobody saw and anybody can
    type.
    """

    @pytest.mark.parametrize(
        "password",
        [
            " " * MIN_PASSWORD_LENGTH,
            "\t" * MIN_PASSWORD_LENGTH,
            "\n" * MIN_PASSWORD_LENGTH,
            "\u00a0" * MIN_PASSWORD_LENGTH,
            " \t\n \u00a0 \t",
            " " * 40,
        ],
        ids=["spaces", "tabs", "newlines", "no-break-spaces", "a-mixture",
             "many-spaces"],
    )
    def test_whitespace_alone_is_refused(self, password):
        """Including U+00A0, which is what a paste out of a document carries.

        ``str.strip()`` is Unicode-aware, so the non-breaking space is
        caught with the plain ones rather than slipping past a rule
        written for ASCII.
        """
        with pytest.raises(ValidationError, match="blank"):
            validate_password(password)

    @pytest.mark.parametrize(
        "password",
        [" correct horse battery staple ", "        x", "x        "],
    )
    def test_a_password_with_content_keeps_its_spaces(self, password):
        """NIST SP 800-63B asks for spaces to be accepted and not trimmed.

        The rule refuses a password that is *only* whitespace; it must not
        become a rule that strips one. ``"        x"`` is nine characters
        and stays nine -- stripped, it would be one and refused as too
        short, which is a different service than the one documented.
        """
        validate_password(password)


class TestANullCharacter:
    """A bcrypt rule rather than a Unicode one.

    bcrypt reads its key as a C string, so everything from the first NUL
    onwards is ignored: a password of eight NULs hashes to something
    ``checkpw(b"", stored)`` accepts -- an account with no password at all
    -- and ``str.strip()`` does not catch it, because NUL
    is not whitespace.
    """

    @pytest.mark.parametrize(
        "password",
        ["\x00" * MIN_PASSWORD_LENGTH, "secret\x00tail", "\x00secret123"],
        ids=["all-nulls", "null-inside", "leading-null"],
    )
    def test_it_is_refused_wherever_it_sits(self, password):
        """Refused anywhere in the value, not only when it is the whole one.

        A password whose tail follows a NUL is a password whose tail does
        not count -- the user would be typing more than the service
        stores, and nothing would say so.
        """
        with pytest.raises(ValidationError, match="null"):
            validate_password(password)


class TestTooLong:

    def test_beyond_the_character_limit_is_refused(self):
        with pytest.raises(ValidationError, match="not exceed"):
            validate_password("a" * (MAX_PASSWORD_LENGTH + 1))

    def test_a_multibyte_password_inside_the_character_limit_can_still_be_refused(self):
        """64 characters, 128 bytes -- past what bcrypt will hash."""
        with pytest.raises(ValidationError, match="not exceed"):
            validate_password("пароль" * 10 + "абвг")

    def test_the_longest_allowed_length_passes(self):
        """The ceiling itself is inside, and only one character past it is
        outside. Checked because ``>`` and ``>=`` differ on exactly this
        password and nowhere else: with the comparison written the wrong
        way the policy refuses a password it advertises as acceptable, and
        every other test in this class stays green."""
        validate_password("a" * MAX_PASSWORD_LENGTH)

    def test_the_byte_ceiling_is_inside_too(self):
        """36 Cyrillic characters are 72 bytes -- the whole of what bcrypt
        hashes, and not one byte more. The character count stays well
        inside its own limit, so this password is refused only if the byte
        comparison is off by one."""
        password = "абвгдеёжзийклмнопрстуфхцчшщъыьэюяабв"[:36]
        assert len(password) == 36
        assert len(password.encode("utf-8")) == MAX_PASSWORD_BYTES

        validate_password(password)

    def test_one_byte_past_the_byte_ceiling_is_refused(self):
        """The same password with one more character: 37 characters, well
        under the character limit, and 74 bytes, which is over."""
        password = "абвгдеёжзийклмнопрстуфхцчшщъыьэюяабвг"[:37]
        assert len(password) < MAX_PASSWORD_LENGTH
        assert len(password.encode("utf-8")) > MAX_PASSWORD_BYTES

        with pytest.raises(ValidationError, match="not exceed"):
            validate_password(password)


class TestPasswordsAttackersAlreadyHave:

    @pytest.mark.parametrize(
        "password",
        # Eight characters or more, so it is the list that refuses them and
        # not the length floor.
        ["password", "12345678", "qwertyui", "iloveyou", "admin123",
         "welcome1", "changeme", "trustno1"],
    )
    def test_a_password_from_the_top_of_every_list_is_refused(self, password):
        with pytest.raises(ValidationError, match="too common"):
            validate_password(password)

    @pytest.mark.parametrize("password", ["Password", "PASSWORD", "PaSsWoRd"])
    def test_changing_the_case_does_not_help(self, password):
        """Every cracking tool folds case by default."""
        with pytest.raises(ValidationError, match="too common"):
            validate_password(password)


class TestOrdinaryPasswordsPass:

    @pytest.mark.parametrize(
        "password",
        [
            "correct horse battery staple",   # long, no composition rules met
            "Test1234!",
            "a-perfectly-ordinary-one",
            "пароль-на-русском",
        ],
    )
    def test_it_is_accepted(self, password):
        validate_password(password)
