"""
Tests for what the service will accept as a password.

Registration used to accept ``short``: the policy bounded only the maximum
length, because it existed to keep a password inside what bcrypt can hash,
and nobody had asked what the floor should be.

The rules follow NIST SP 800-63B: a length floor and a check against
passwords attackers already have, and deliberately no composition rules --
"must contain a digit and a symbol" produces ``Password1!``, which is early
in every cracking list, while refusing a long passphrase, which is not.
"""

import pytest

from link_shortener.domain.exceptions import ValidationError
from link_shortener.domain.policies.password_policy import (
    MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH, validate_password
)


class TestTooShort:

    @pytest.mark.parametrize("password", ["", "a", "short", "1234567"])
    def test_it_is_refused(self, password):
        with pytest.raises(ValidationError, match="at least"):
            validate_password(password)

    def test_the_shortest_allowed_length_passes(self):
        validate_password("h" * MIN_PASSWORD_LENGTH)


class TestTooLong:

    def test_beyond_the_character_limit_is_refused(self):
        with pytest.raises(ValidationError, match="not exceed"):
            validate_password("a" * (MAX_PASSWORD_LENGTH + 1))

    def test_a_multibyte_password_inside_the_character_limit_can_still_be_refused(self):
        """64 characters, 128 bytes -- past what bcrypt will hash."""
        with pytest.raises(ValidationError, match="not exceed"):
            validate_password("пароль" * 10 + "абвг")


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
