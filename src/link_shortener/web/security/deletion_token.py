"""
Proof that the holder is the one who created a guest link.

A link made without an account has no owner, so ``link:delete_own`` has
nothing to compare against and can never match: the person who shortened
something by mistake could not take it back, and only a holder of
``link:delete_any`` could. It sat there until its expiry, seven days by
default.

The address it was created from is not the answer. It changes, and it is
shared: behind one NAT, "the same address" is a different person as often
as it is the same one, so an IP check would refuse the creator and admit a
stranger.

What is left is a secret handed to whoever created the link, which is what
this is: the link's identifier, signed, returned once in the creation
response and accepted afterwards as proof. Nothing is stored -- the
signature is the record.

The *identifier* is signed, not the short code, and that is load-bearing.
Codes are freed by deletion and can be issued again, so a token naming a
code would go on being valid for whatever link took that code next.
"""

from typing import Optional

from itsdangerous import BadSignature, URLSafeSerializer


SALT = b"link-deletion-token"
"""Domain separation: this signature cannot be used as any other."""


def issue(secret_key: str, link_id: str) -> str:
    """
    Mint the token for a newly created link.

    Args:
        secret_key: Application signing key.
        link_id: Identifier of the link the token deletes.

    Returns:
        The token, to be returned to the creator once.
    """
    return _serializer(secret_key).dumps(link_id)


def link_id_from(secret_key: str, token: Optional[str]) -> Optional[str]:
    """
    Recover the link a token was issued for.

    Args:
        secret_key: Application signing key.
        token: Token presented by the client, or ``None``.

    Returns:
        The link identifier, or ``None`` if the token is absent, forged, or
        signed with another key. There is deliberately no age limit: the
        token is worth exactly one link, and that link's own expiry ends it.
    """
    if not token:
        return None

    try:
        return _serializer(secret_key).loads(token)
    except BadSignature:
        return None


def _serializer(secret_key: str) -> URLSafeSerializer:
    """
    Build the serializer for this token type.

    Args:
        secret_key: Application signing key.

    Returns:
        A configured serializer.
    """
    return URLSafeSerializer(secret_key, salt=SALT)
