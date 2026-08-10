from typing import Callable

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
    registering it again is refused because the account exists, and nobody
    can sign in to it because signing in needs a confirmed address. Left
    unrun, this is a way for anyone to reserve addresses they do not own,
    permanently, and the owners are simply told the address is taken.

    Args:
        use_case: CleanUnverifiedAccountsUseCase instance.
        context: Request context.

    Returns:
        Number of deleted accounts.
    """
    return use_case.execute(context)
