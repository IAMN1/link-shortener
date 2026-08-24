from collections import Counter
from typing import Any, Dict, List, cast as as_type

from sqlalchemy import CursorResult, text
from sqlalchemy.exc import IntegrityError

from link_shortener.application import (
    UnitOfWorkFactory, RequestContext, CleanExpiredLinksUseCase,
    CleanUnverifiedAccountsUseCase
)
from link_shortener.domain.value_objects.email import Email
from link_shortener.infrastructure.database.manager import DatabaseManager


def what_the_database_said(error: BaseException) -> str:
    """
    Render a database error as one line an operator can read.

    SQLAlchemy puts the statement and its parameters into the rest of the
    message, and the parameters here are people's addresses, which would
    otherwise reach the terminal and whatever log a scheduled run writes
    to.

    The first line that says anything, rather than ``splitlines()[0]``:
    an exception raised with no message has no first line, and one whose
    text begins with a newline would lose its only sentence.

    Args:
        error: The exception to describe.

    Returns:
        The first line that says anything, or the exception's class name
        when it says nothing at all.
    """
    for line in str(error).splitlines():
        if line.strip():
            return line.strip()

    return type(error).__name__


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


def clean_expired_sessions(uow_factory: UnitOfWorkFactory) -> int:
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


def clean_expired_password_resets(uow_factory: UnitOfWorkFactory) -> int:
    """
    Delete reset tokens that can no longer be spent.

    Both halves go: expired, and already used. A spent token is as dead as
    an expired one, and neither grants anything -- what they do is
    accumulate, one row per request, in a table nothing else prunes.
    Confirmation tokens are swept by ``clean-unverified``, alongside the
    accounts they belong to; these belong to accounts that are staying, so
    they need a job of their own.

    Args:
        uow_factory: Factory for creating Unit of Work instances.

    Returns:
        Number of deleted tokens.
    """
    with uow_factory() as uow:
        deleted = uow.password_resets.delete_expired()
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


def find_addresses_needing_normalising(
    db_manager: DatabaseManager,
) -> List[Dict[str, Any]]:
    """
    List stored addresses that are not in lower case.

    Read with SQL rather than through the repository because this needs
    two columns for every account in one pass, where ``list_all`` pages
    and builds a whole ``User`` aggregate per row.

    Which rows need work is decided by ``Email.normalise`` rather than by
    SQL ``lower()``: the two agree on PostgreSQL and part ways on SQLite,
    whose ``lower()`` is ASCII-only, so the whole table is read and
    filtered in Python.

    A row is reported as clashing when another account's address lowers
    to the same string. Those are left alone -- merging two accounts is
    an owner's decision about whose links, roles and sessions survive.

    Args:
        db_manager: Database manager providing sessions.

    Returns:
        One dict per address, with ``id``, ``email`` and ``clashes``.
    """
    with db_manager.session() as session:
        rows = session.execute(
            text("SELECT id, email FROM users ORDER BY email")
        ).mappings().all()

    # Counted over every account, not only over the ones needing work: a
    # row can collide with an address that is already normalised, and
    # that one never appears in the result below.
    normalised = Counter(Email.normalise(r["email"]) for r in rows)

    return [
        {
            "id": r["id"],
            "email": r["email"],
            "clashes": normalised[Email.normalise(r["email"])] > 1,
        }
        for r in rows
        if r["email"] != Email.normalise(r["email"])
    ]


def normalise_addresses(
    db_manager: DatabaseManager, rows: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Lower the stored addresses that can be lowered without collision.

    Needed because ``Email`` started lowering addresses after these rows
    were written: a stored ``Case@Example.com`` is no longer found by a
    lookup for it, so its owner cannot sign in and cannot register again
    either.

    One transaction per address rather than one for all of them, so a row
    the database refuses leaves the rest migrated. Every error is caught
    per row and what the database said travels back in ``reasons``.

    The new value is computed by ``Email.normalise`` and sent as a
    parameter rather than written as SQL ``lower(email)``, so the row
    selected by one rule is not rewritten by another. The write matches
    on the stored address as well as the id: the owner may have changed
    it between the read and the write, and that address is not one to
    overwrite with a lowered copy of the old one.

    Args:
        db_manager: Database manager providing sessions.
        rows: The addresses to work through, as
            ``find_addresses_needing_normalising`` reports them -- the
            same list the caller showed the operator.

    Returns:
        ``{"changed", "skipped", "refused", "failed", "moved",
        "remaining", "reasons"}`` -- lowered; left alone as a known
        collision; refused by the unique index; failed for any other
        reason; gone or changed by somebody else between the read and the
        write; how many addresses were never attempted, which only a
        ``Ctrl-C`` can leave above zero; and the distinct error texts
        behind ``failed``.
    """
    doomed = [
        (row["id"], row["email"], Email.normalise(row["email"]))
        for row in rows
        if not row["clashes"]
    ]
    skipped = len(rows) - len(doomed)

    changed = 0
    refused = 0
    failed = 0
    moved = 0
    reasons: List[str] = []

    for user_id, stored, normalised in doomed:
        counted = False
        try:
            with db_manager.session() as session:
                # Named as what a statement with no rows to return
                # actually produces, the way the repositories that read
                # ``rowcount`` do it: ``Session.execute`` is declared to
                # return ``Result``, which has no such attribute, so the
                # count below is unreachable to the checker until this is
                # said. The object is the same one either way.
                result = as_type(
                    CursorResult,
                    session.execute(
                        text(
                            "UPDATE users SET email = :email "
                            "WHERE id = :id AND email = :stored"
                        ),
                        {"id": user_id, "email": normalised, "stored": stored},
                    ),
                )
                session.commit()

                # Counted inside the block that owns the outcome, so an
                # error on the way out of the context cannot undo the
                # count of a row already committed. A write that matched
                # nothing is not a change: the row may have been deleted
                # or its address changed by its owner in between.
                if result.rowcount:
                    changed += 1
                else:
                    moved += 1
                counted = True
        except IntegrityError:
            if not counted:
                refused += 1
        except KeyboardInterrupt:
            # Ctrl-C stops the work and not the report: the rows already
            # lowered are counted, and the remainder tells the operator
            # what is still to do.
            break
        except Exception as error:
            # Everything, not ``SQLAlchemyError``: a driver exception the
            # ORM never wrapped is not one, and it would end the run with
            # rows silently written and no counter printed.
            if not counted:
                failed += 1
                # The first line only: SQLAlchemy renders the statement
                # and its parameters into the rest of the message, and
                # the parameters here are addresses.
                reason = what_the_database_said(error)
                if reason not in reasons:
                    reasons.append(reason)

    attempted = changed + moved + refused + failed
    return {
        "changed": changed,
        "skipped": skipped,
        "refused": refused,
        "failed": failed,
        "moved": moved,
        "remaining": len(doomed) - attempted,
        "reasons": reasons,
    }
