"""The secret that proves someone reads a mailbox, and what is kept of it.

Two of the five rules OWASP's Forgot Password Cheat Sheet states for a
token mailed to a user live here: generate it with a cryptographically
secure source, and make it long enough to resist brute force. (The other
three -- linked to a user, invalidated after use, expiring -- are
properties of a stored row and belong to ``EmailVerification`` and
``PasswordReset``, which is why both keep one.)

On storage the cheat sheet says "Stored in a secure manner, as discussed
in the Password Storage Cheat Sheet", and this deliberately does something
else: a plain SHA-256 digest rather than a slow password hash. A password
is guessable because a person chose it, so its hash has to be expensive to
compute. This token is 256 bits from ``secrets``, so there is no guessing
to slow down -- the digest is here for the other reason, that a leaked
database row must not be usable as the link it stands for. Stated as a
departure rather than as compliance, because the source points the other
way.
"""

import hashlib
import secrets


TOKEN_BYTES = 32
"""Bytes of entropy in a mailed token, of either kind.

256 bits, which is not a number to be tuned. It is what makes the digest
below safe as a plain hash, and what makes brute force meaningless against
a table that has an index on the digest.
"""

DIGEST_LENGTH = 64
"""Characters in the stored digest: SHA-256 rendered as hex.

Stated as a constant because a column has to be exactly this wide. The ORM
model imports it; the migration repeats the number, because a revision is
a record of what was applied and must not change under a later edit --
so the two are compared against each other by
``tests/integration/infrastructure/database/test_schema_matches_migration.py``.

A narrower column raises on PostgreSQL. On SQLite, which ignores declared
widths entirely, it would store the digest anyway -- which is worse, since
the deployment fails and the developer's machine does not.
"""


def issue_token() -> str:
    """
    Mint a fresh confirmation token.

    Returns:
        The token, URL-safe, to be mailed and never stored.
    """
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_digest(token: str) -> str:
    """
    Reduce a token to the form that is safe to keep.

    Args:
        token: The token as it appears in the confirmation link.

    Returns:
        Lowercase hex SHA-256 digest, ``DIGEST_LENGTH`` characters.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
