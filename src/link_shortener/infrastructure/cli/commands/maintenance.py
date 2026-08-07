from typing import Callable

from link_shortener.application import (
    RequestContext, CleanExpiredLinksUseCase, UnitOfWork
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
