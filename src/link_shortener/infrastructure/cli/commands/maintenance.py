from link_shortener.application import RequestContext, CleanExpiredLinksUseCase


def clean_expired_links(
    use_case: CleanExpiredLinksUseCase, days: int, context: RequestContext
) -> int:
    """
    Delete links that have not been accessed for more than `days` days.

    Args:
        use_case: CleanExpiredLinksUseCase instance.
        days: Age threshold in days.
        context: Request context.

    Returns:
        Number of deleted links.
    """
    return use_case.execute(days, context)
