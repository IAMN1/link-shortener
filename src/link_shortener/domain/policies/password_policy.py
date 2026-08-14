"""
Password rules owned by the domain.

The rules live here rather than in the hashing service so that what is
stated to the user is a product decision, not a detail of whichever hashing
library happens to be wired in. A message naming the library's own limit
would tell an anonymous caller which algorithm guards the passwords.

What is checked, and why it is only this: NIST SP 800-63B asks for a length
floor and a check against passwords already known to attackers, and asks
*against* composition rules -- "must contain a digit and a symbol" pushes
people towards ``Password1!``, which a dictionary attack tries early, while
refusing ``correct horse battery staple``, which it does not. Length is the
property that actually costs an attacker work.
"""

from link_shortener.domain.exceptions import ValidationError


MIN_PASSWORD_LENGTH = 8
"""Shortest password the service accepts, in characters (NIST SP 800-63B)."""

MAX_PASSWORD_LENGTH = 64
"""Longest password the service accepts, in characters."""

MAX_PASSWORD_BYTES = 72
"""
Upper bound in UTF-8 bytes.

Kept as a second guard because a password within the character limit can
still exceed it when built from multi-byte characters.
"""

COMMON_PASSWORDS = frozenset({
    "password", "password1", "password12", "password123", "passw0rd",
    "123456", "1234567", "12345678", "123456789", "1234567890",
    "12345678910", "111111", "1111111", "11111111", "000000", "00000000",
    "123123", "123321", "112233", "121212", "654321", "666666", "888888",
    "abc123", "abcd1234", "a1b2c3d4", "qwerty", "qwerty1", "qwerty12",
    "qwerty123", "qwertyui", "qwertyuiop", "1q2w3e4r", "1qaz2wsx",
    "zaq12wsx", "asdfghjk", "asdfghjkl", "qazwsx", "qazwsxedc",
    "iloveyou", "princess", "sunshine", "football", "baseball",
    "superman", "batman", "trustno1", "letmein", "welcome", "welcome1",
    "monkey", "monkey123", "dragon", "master", "shadow", "michael",
    "jennifer", "jordan23", "hunter2", "starwars", "computer", "internet",
    "samsung", "google", "facebook", "whatever", "freedom", "charlie",
    "andrew", "thomas", "robert", "daniel", "matthew", "joshua",
    "admin", "admin123", "administrator", "root", "toor", "user",
    "guest", "test", "test123", "testtest", "changeme", "default",
    "secret", "secret123", "login", "passwd", "pass123", "temp123",
    "linkshortener", "shortener",
})
"""Passwords an attacker tries in the first seconds, and so cannot be used.

A short embedded list rather than a breach corpus, which is the honest
version of this check: HIBP's is 850 MB and is queried over the network,
and neither belongs in a domain policy. What this catches is the top of
every cracking list; what it does not catch is a password that is merely
weak. Stated rather than implied, because a check like this reads as more
protection than it gives.
"""


def validate_password(password: str) -> None:
    """
    Reject a password the service will not accept.

    Args:
        password: Raw password.

    Raises:
        ValidationError: If the password is blank, too short, too long, or
            one an attacker would try immediately.
    """
    # Length alone does not catch this: eight spaces are eight characters
    # and clear every bar below. `flask create-admin` asks for the
    # password with the input hidden, so a held-down space bar would
    # create the most privileged account in the service with a password
    # nobody can see and anybody can guess.
    #
    # `str.strip()` is Unicode-aware, so a value made of tabs, newlines or
    # non-breaking spaces is caught with the plain ones. The value itself
    # is never stripped: NIST SP 800-63B asks for spaces to be accepted
    # inside a password and for verifiers not to truncate, so
    # " my pass phrase " stays exactly that, trailing space included, and
    # that space keeps counting towards the length.
    if not password.strip():
        raise ValidationError(
            "Password must not be blank",
            field="password",
        )

    # Not a Unicode rule but a bcrypt one, and the only invisible
    # character worth naming. bcrypt reads its key as a C string, so
    # everything from the first NUL onwards is ignored, so a password of
    # eight NULs hashes to something `checkpw(b"", stored)` accepts --
    # an account with no password at all.
    if "\x00" in password:
        raise ValidationError(
            "Password must not contain a null character",
            field="password",
        )

    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters",
            field="password",
        )

    # One message for two ceilings, and the wording has to fit both. The
    # byte limit bites first for anything outside Latin -- 37 Cyrillic
    # characters are 74 bytes -- and a bare "must not exceed 64
    # characters" then states a number the password does not have. Naming
    # the byte limit outright is what this module refuses to do: it is the
    # hashing library's, and a message quoting it tells an anonymous
    # caller which algorithm is in use -- and a test in
    # `test_auth_controller` holds the endpoint to that, refusing the
    # words "byte", "72", "bcrypt" and "truncate" in any answer.
    if (
        len(password) > MAX_PASSWORD_LENGTH
        or len(password.encode("utf-8")) > MAX_PASSWORD_BYTES
    ):
        raise ValidationError(
            f"Password must not exceed {MAX_PASSWORD_LENGTH} characters, "
            "and fewer for alphabets that need more room per character",
            field="password",
        )

    # Compared in lower case: "Password123" is the same guess as
    # "password123" to anyone running a list through a case-folding rule,
    # which every cracking tool does by default.
    if password.lower() in COMMON_PASSWORDS:
        raise ValidationError(
            "Password is too common -- choose one that is not on every "
            "attacker's list",
            field="password",
        )
