"""What a CSRF token has to be, and how long it stays one.

``verify_csrf_token`` is where the double-submit scheme stops being plain
double submit. A cookie value echoed in a header proves only that the two
agree, which anyone able to write a cookie on the domain can arrange; the
signature is what they cannot produce without ``SECRET_KEY``, and the
issue time inside the signed message is what stops a value that leaked
from being worth anything for ever.

The module says so -- "a leaked value stops working once
``CSRF_TOKEN_TTL_SECONDS`` have passed rather than lasting forever" -- and
nothing measured it. Nor the shapes a token can arrive in: three parts
and no more, a nonce and a signature that are actually there, and a
middle field that is a number. Each of those returns ``False`` on a line
the suite never reached, and a guard nothing exercises is a guard that
can be inverted without anything going red.

Read at this level rather than through a request because the ageing is
the subject: driving it through the application would mean either
waiting twelve hours or reaching past the thing being tested to move the
clock.
"""

import time

import pytest

from link_shortener.web.middleware.csrf import (
    CSRF_TOKEN_TTL_SECONDS,
    _signature,
    build_csrf_token,
    verify_csrf_token,
)


SECRET = "the-signing-key"
USER = "user-under-test"


def token_issued_at(issued_at: int, user_id: str = USER) -> str:
    """
    Mint a token as the service would have minted it at a chosen moment.

    Built through ``_signature`` rather than by editing a real token,
    because the issue time is inside the signed message: a token with its
    middle field rewritten is a token with a broken signature, and would
    be refused for the wrong reason.

    Args:
        issued_at: Unix timestamp to mint it at.
        user_id: Account it is issued to.

    Returns:
        A token of the form ``<nonce>.<issued_at>.<signature>``.
    """
    nonce = "a-nonce-of-no-importance"
    return f"{nonce}.{issued_at}.{_signature(SECRET, user_id, nonce, issued_at)}"


class TestAgeing:

    def test_a_fresh_token_is_accepted(self):
        assert verify_csrf_token(SECRET, USER, build_csrf_token(SECRET, USER))

    def test_a_token_just_inside_the_window_is_accepted(self):
        issued = int(time.time()) - (CSRF_TOKEN_TTL_SECONDS - 60)

        assert verify_csrf_token(SECRET, USER, token_issued_at(issued))

    def test_a_token_past_the_window_is_refused(self):
        """A form left open overnight, and a value that leaked with it."""
        issued = int(time.time()) - (CSRF_TOKEN_TTL_SECONDS + 60)

        assert not verify_csrf_token(SECRET, USER, token_issued_at(issued))

    def test_the_issue_time_cannot_be_pushed_forward(self):
        """It is inside the signed message, so rewriting it breaks the seal.

        This is the whole reason the timestamp travels signed rather than
        beside the signature: whoever holds an aged-out token would
        otherwise only have to edit three digits.
        """
        aged = token_issued_at(int(time.time()) - CSRF_TOKEN_TTL_SECONDS * 2)
        nonce, _, signature = aged.split(".")
        forged = f"{nonce}.{int(time.time())}.{signature}"

        assert not verify_csrf_token(SECRET, USER, forged)


class TestTheShapeOfIt:

    @pytest.mark.parametrize("token", [
        "",
        "one-part",
        "two.parts",
        "four.parts.here.now",
        # The nonce and the signature are both there or the token is not
        # a token; empty either side used to reach `compare_digest`.
        ".12345.abc",
        "nonce.12345.",
        # A middle field that is not a number at all.
        "nonce.not-a-number.abc",
        "nonce..abc",
    ])
    def test_a_malformed_token_is_refused(self, token):
        assert not verify_csrf_token(SECRET, USER, token)

    def test_a_token_carrying_non_ascii_is_refused_not_crashed(self):
        """``compare_digest`` raises on non-ASCII ``str``.

        The comparison is done on bytes for that reason, and the module
        says so. Left as strings, a forged token would come back 500 --
        a crash where a refusal belongs, and one an attacker can trigger
        with a single character.
        """
        assert not verify_csrf_token(SECRET, USER, "nonce.12345.подпись")


class TestWhoItWasIssuedTo:

    def test_another_account_cannot_present_it(self):
        """The signature binds the token to one account.

        Without it the scheme is plain double submit again: on the
        endpoints that read a cookie themselves, a request can carry
        somebody else's valid header credential alongside the victim's
        cookies.
        """
        theirs = build_csrf_token(SECRET, "somebody-else")

        assert not verify_csrf_token(SECRET, USER, theirs)

    def test_another_key_cannot_mint_one(self):
        assert not verify_csrf_token(
            SECRET, USER, build_csrf_token("a-different-key", USER)
        )
