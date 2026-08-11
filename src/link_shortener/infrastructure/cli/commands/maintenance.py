from typing import Any, Callable, Dict, List

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from link_shortener.application import (
    RequestContext, CleanExpiredLinksUseCase, CleanUnverifiedAccountsUseCase,
    UnitOfWork
)


def clean_expired_links(
    use_case: CleanExpiredLinksUseCase, context: RequestContext
) -> int:
    """
    Delete links whose expiry has passed.

    Args:
        use_case: CleanExpiredLinksUseCase instance.
        context: Request context.

    Returns:
        Number of deleted links.
    """
    return use_case.execute(context)


def clean_expired_sessions(uow_factory: Callable[[], UnitOfWork]) -> int:
    """
    Delete refresh sessions whose tokens have expired.

    An expired row grants nothing, but one is written per issued refresh
    token, so without periodic cleanup the table only grows.

    Args:
        uow_factory: Factory for creating Unit of Work instances.

    Returns:
        Number of deleted sessions.
    """
    with uow_factory() as uow:
        deleted = uow.refresh_sessions.delete_expired()
        uow.commit()
        return deleted


def clean_unverified_accounts(
    use_case: CleanUnverifiedAccountsUseCase, context: RequestContext
) -> int:
    """
    Delete registrations nobody confirmed within the configured window.

    Not optional housekeeping. An unconfirmed account holds its address:
    registering it again creates nothing, because the account exists, and
    nobody can sign in to it because signing in needs a confirmed address.
    Left unrun, this is a way for anyone to reserve addresses they do not
    own, permanently -- and since registration stopped saying whether an
    address is taken, the owner is not even told that much. They are told
    a link has been sent, and receive a notice that the account already
    exists, which is not one they can get into.

    Args:
        use_case: CleanUnverifiedAccountsUseCase instance.
        context: Request context.

    Returns:
        Number of deleted accounts.
    """
    return use_case.execute(context)


def find_addresses_needing_normalising(db_manager) -> List[Dict[str, Any]]:
    """
    List stored addresses that are not in lower case.

    Read with SQL rather than through the repository on purpose. ``Email``
    lowers what it is given, including what it is built from on the read
    path, so an account stored as ``Case@Example.com`` comes back through
    the domain as ``case@example.com`` -- and the very rows this looks for
    would be invisible.

    Each row is reported with whether lowering it would collide -- that
    is, whether any other account's address lowers to the same string.
    Those are left alone: merging two accounts means deciding which links,
    roles and sessions survive, and that is an owner's decision, not a
    migration's.

    The comparison is between lowered forms on both sides, which is not
    where this started. Asking only whether the lower-case spelling is
    *already stored* missed the pair that has no lower-case member at all:
    ``Case@Example.com`` and ``CASE@Example.com`` were both reported safe,
    the update hit the unique index, and the whole run rolled back --
    leaving every unrelated address unmigrated and the operator told
    there had been no conflicts.

    Args:
        db_manager: Database manager providing sessions.

    Returns:
        One dict per address, with ``id``, ``email`` and ``clashes``.
    """
    with db_manager.session() as session:
        rows = session.execute(
            text(
                "SELECT u.id, u.email, "
                "(SELECT COUNT(*) FROM users o "
                "  WHERE lower(o.email) = lower(u.email)) > 1 AS clashes "
                "FROM users u WHERE u.email <> lower(u.email) "
                "ORDER BY u.email"
            )
        ).mappings().all()

    return [
        {"id": r["id"], "email": r["email"], "clashes": bool(r["clashes"])}
        for r in rows
    ]


def normalise_addresses(db_manager) -> Dict[str, int]:
    """
    Lower the stored addresses that can be lowered without collision.

    Needed because ``Email`` started lowering addresses after these rows
    were written: a stored ``Case@Example.com`` is no longer found by a
    lookup for it, so its owner cannot sign in and cannot register again
    either -- registration would find nothing and create a second account
    for the same mailbox.

    Rows that collide with another account are skipped, and
    ``find_addresses_needing_normalising`` reports them so an operator can
    deal with them deliberately.

    One transaction per address rather than one for all of them. A single
    failure used to roll the whole run back, so one bad pair left every
    other account unmigrated; and the index can refuse a row for a reason
    this function cannot see in advance -- somebody registering the
    lower-case spelling while the command runs.

    Args:
        db_manager: Database manager providing sessions.

    Returns:
        ``{"changed": n, "skipped": n, "refused": n}`` -- lowered, left
        alone as a known collision, and refused by the index anyway.
    """
    rows = find_addresses_needing_normalising(db_manager)
    doomed = [row["id"] for row in rows if not row["clashes"]]
    skipped = len(rows) - len(doomed)

    changed = 0
    refused = 0
    for user_id in doomed:
        try:
            with db_manager.session() as session:
                session.execute(
                    text(
                        "UPDATE users SET email = lower(email) WHERE id = :id"
                    ),
                    {"id": user_id},
                )
                session.commit()
            changed += 1
        except IntegrityError:
            refused += 1

    return {"changed": changed, "skipped": skipped, "refused": refused}
