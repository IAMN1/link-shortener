from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DedupScope:
    """
    Value object naming the set of links a URL may deduplicate against.

    Two links are duplicates of each other only when they share both the URL
    hash and this scope. Matching on the hash alone handed the caller a link
    belonging to somebody else: they could not list it, delete it or read its
    statistics, and when the first shortener had been a guest, the link they
    "created" expired under them seven days later.

    A registered account is a scope of its own. A guest is scoped by the
    identifier their links are already counted under, so two visitors never
    inherit each other's links. Links created with neither -- from the CLI,
    where there is no request and no owner -- share the anonymous scope.

    Attributes:
        owner_id: The owning account, or ``None`` for links with no owner.
        guest_identifier: Identifier a guest's links are grouped by (an IP
            address), or ``None``.
    """

    owner_id: Optional[str] = None
    guest_identifier: Optional[str] = None

    def __post_init__(self):
        """
        Drop the guest identifier of an owned scope.

        Ownership wins. An account's links are scoped by the account, and
        keeping an address alongside it would split one owner's links into
        per-address scopes that never dedupe against each other.
        """
        if self.owner_id is not None:
            object.__setattr__(self, "guest_identifier", None)

    @classmethod
    def for_guest(cls, guest_identifier: Optional[str]) -> "DedupScope":
        """
        Build the scope of an unauthenticated caller.

        Args:
            guest_identifier: Identifier the guest's links are counted under,
                or ``None`` when the caller has none (the anonymous scope).

        Returns:
            The corresponding scope.
        """
        return cls(guest_identifier=guest_identifier)

    @classmethod
    def for_owner(cls, owner_id: str) -> "DedupScope":
        """
        Build the scope of a registered account.

        Args:
            owner_id: UUID of the owning user.

        Returns:
            The corresponding scope.
        """
        return cls(owner_id=owner_id)

    def token(self) -> str:
        """
        Return a stable string naming this scope, for use in cache keys.

        The kind is spelled out in the prefix so that an account id and a
        guest identifier can never produce the same token -- a cache entry
        answering for the wrong scope is exactly the mix-up this object
        exists to prevent.

        Returns:
            ``u:<owner id>``, ``g:<guest identifier>`` or ``anon``.
        """
        if self.owner_id is not None:
            return f"u:{self.owner_id}"
        if self.guest_identifier is not None:
            return f"g:{self.guest_identifier}"
        return "anon"
