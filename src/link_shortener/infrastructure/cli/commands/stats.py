from link_shortener.application import (
    RequestContext, GetServiceStatsUseCase, ServiceStatsResponse, StatsCache
)


def refresh_stats(
    use_case: GetServiceStatsUseCase,
    stats_cache: StatsCache,
    context: RequestContext,
) -> ServiceStatsResponse:
    """
    Force a fresh retrieval of service statistics and update the cache.

    The cached entry is dropped first: the use case answers from the cache
    on a hit, so without the drop this command would print "STATISTIC
    REFRESHED IN CACHE" above the same numbers it was handed.

    The use case's own response is handed back rather than unpacked into a
    dictionary. Flattening it here cost the caller its types and put the
    field names into strings, where a misspelling is a ``KeyError`` at the
    moment somebody runs the command.

    Args:
        use_case: GetServiceStatsUseCase instance.
        stats_cache: Cache holding the service-wide totals.
        context: Request context, naming the command that asked. Built by
            the adapter, as every other command's is: which command a
            record belongs to is the adapter's fact, and these two were
            the only ones naming themselves from down here.

    Returns:
        The service-wide statistics.
    """
    stats_cache.delete_stats()
    return use_case.execute(context)


def get_stats(
    use_case: GetServiceStatsUseCase, context: RequestContext
) -> ServiceStatsResponse:
    """
    Retrieve service statistics (may be from cache).

    Args:
        use_case: GetServiceStatsUseCase instance.
        context: Request context, naming the command that asked. It was
            optional, defaulting to a context built here -- and no caller
            ever passed one, so the default was the only thing that ran
            and the command's name lived in the wrong layer.

    Returns:
        The service-wide statistics.
    """
    return use_case.execute(context)
