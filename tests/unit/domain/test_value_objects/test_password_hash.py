"""What the hash object promises, and the one shape that breaks it.

``PasswordHash`` held any string at all, including the empty one. Nothing
in the service produces an empty hash today, so nothing was measurably
wrong -- and that is what made it worth closing rather than leaving: the
damage an empty hash does is silent. ``bcrypt.checkpw`` refuses it, so the
account it belongs to answers "wrong password" to its owner and to
everybody else, for ever, with no failure recorded anywhere and nothing
to distinguish it from somebody mistyping.

The value stays otherwise opaque on purpose. A check for ``$2b$`` or for
a length would be a check about bcrypt, and the whole reason the domain
holds a hash rather than a bcrypt digest is that the algorithm is
somebody else's decision.
"""

import pytest

from link_shortener.domain.value_objects.password_hash import PasswordHash


BCRYPT = "$2b$12$KIXQ0hZ8Yy4b7Q8FbF5m4uJvJ0z1Zx2Yv3Wq4Rt5Uy6Ii7Oo8Pp9"
"""A hash of the shape the service actually stores."""


class TestAHashThatHashesNothingIsRefused:

    @pytest.mark.parametrize("value", ["", "   ", "\t", "\n", "   "])
    def test_an_empty_value_is_refused(self, value):
        with pytest.raises(ValueError):
            PasswordHash(value)

    def test_the_refusal_is_a_value_error_and_not_a_domain_one(self):
        """Nobody types a hash, so an empty one is nobody's bad request.

        The web layer has no handler for ``ValueError`` on purpose: it
        falls through to the 500 handler, which logs the traceback and
        tells the caller nothing. Raised as a ``ValidationError`` this
        would be answered 400 -- "your request was bad" to a caller whose
        request was fine.
        """
        from link_shortener.domain.exceptions import DomainError

        with pytest.raises(ValueError) as raised:
            PasswordHash("")

        assert not isinstance(raised.value, DomainError)


class TestEveryOtherValueIsHeldAsGiven:

    def test_a_real_hash_is_kept_exactly(self):
        assert PasswordHash(BCRYPT).value == BCRYPT

    def test_the_string_form_is_the_value(self):
        assert str(PasswordHash(BCRYPT)) == BCRYPT

    @pytest.mark.parametrize("value", [
        # Not bcrypt. The domain does not know which algorithm is wired
        # in, and refusing these would be refusing a future one.
        "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$aGFzaA",
        "$2y$10$abcdefghijklmnopqrstuv",
        "not-a-hash-but-not-empty",
    ])
    def test_a_hash_from_another_algorithm_is_accepted(self, value):
        assert PasswordHash(value).value == value
