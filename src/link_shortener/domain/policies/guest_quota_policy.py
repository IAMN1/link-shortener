"""
How many links a guest may still create, and the refusal when none are left.

The rule lived twice, in two shapes: the single-link path asked whether the
count had reached the limit, the batch path worked out how many were left,
and each built the refusal itself -- the same sentence written three times
across two files. A quota whose arithmetic is spelt out at every call site
is a quota that drifts: change the window to hours here and the other place
still counts days, and nothing fails until a guest notices they may create
twice as many links through one endpoint as through the other.
"""

from link_shortener.domain.exceptions import GuestLinkLimitExceededError
from link_shortener.domain.i18n import N_


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

    Returned rather than raised: the single-link path raises it, and the
    batch path carries it per item inside a 200. One sentence either way,
    which is the point of building it here.

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
