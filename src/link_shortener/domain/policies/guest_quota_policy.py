"""
How many links a guest may still create, and the refusal when none are left.

The rule lived twice, in two shapes: the single-link path asked whether the
count had reached the limit, the batch path worked out how many were left,
and each built the refusal itself -- the same sentence written three times
across two files. A quota whose arithmetic is spelt out at every call site
is a quota that drifts: change the window to hours here and the other place
still counts days, and nothing fails until a guest notices they may create
twice as many links through one endpoint as through the other.

The arithmetic came here first and the reading of it followed, because the
two call sites turned out to differ only in the question they put to the
answer. Both still had to lock, count and subtract, in that order and for
reasons neither spelt out fully -- so the order was written twice and could
have been got wrong in one place without anything noticing.
"""

from link_shortener.domain.exceptions import GuestLinkLimitExceededError
from link_shortener.domain.i18n import N_
from link_shortener.domain.repositories.link_repository import LinkRepository


def links_left_for_guest(used: int, limit: int) -> int:
    """
    How many links this guest may still create.

    Args:
        used: Links the guest has created inside the window.
        limit: Links the guest is allowed inside the window.

    Returns:
        The remainder, never below zero -- a guest who is over the limit
        (a limit lowered under them, say) may create none rather than a
        negative number of links.
    """
    return max(0, limit - used)


def guest_quota_spent(limit: int, window_days: int) -> GuestLinkLimitExceededError:
    """
    Build the refusal a guest gets when the allowance is gone.

    Returned rather than raised, because the callers do different things
    with it. The single-link path raises it. The batch path does both: it
    carries one per item inside a 200 where part of the batch got through,
    and raises it where the quota refused every item and nothing else in
    the request got done. One sentence in all three places, which is the
    point of building it here.

    Args:
        limit: Links allowed inside the window.
        window_days: How long the window lasts, in days.

    Returns:
        The refusal, carrying how long until it is worth trying again.
    """
    return GuestLinkLimitExceededError(
        f"Guest link limit of {limit} exceeded.",
        retry_after_seconds=window_days * 24 * 3600,
        template=N_("Guest link limit of %(limit)s exceeded."),
        params={"limit": limit},
    )


def guest_allowance(
    repository: LinkRepository,
    guest_id: str,
    limit: int,
    window_days: int,
) -> int:
    """Read what this guest has left, in a way another request cannot spend.

    Three steps that only make sense together, and that both creation paths
    took separately. Counting and inserting are two statements: without the
    lock, every simultaneous request from one guest reads the same allowance
    and spends it in full, which is worth an entire quota per caller to
    anyone sending batches.

    Called inside the transaction that goes on to insert, not before it. It
    does not make the count atomic -- the insert still follows the read --
    but an allowance read in a unit of work that has already closed leaves a
    window as wide as the whole lookup.

    On engines without such a lock -- SQLite, i.e. local development and the
    test suite -- the limit is advisory.

    Args:
        repository: The links, in the transaction about to write.
        guest_id: Identifier this guest's links are counted under.
        limit: Links the guest is allowed inside the window.
        window_days: How long the window lasts, in days.

    Returns:
        How many links the guest may still create, never below zero.
    """
    repository.lock_guest_quota(guest_id)
    used = repository.count_guest_links_by_identifier(guest_id, window_days)
    return links_left_for_guest(used, limit)
