from typing import Optional

from link_shortener.application import (
    RequestContext, GetServiceStatsUseCase, ServiceStatsResponse, StatsCache
)


def refresh_stats(
    use_case: GetServiceStatsUseCase, stats_cache: StatsCache
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

    Returns:
        The service-wide statistics.
    """
    stats_cache.delete_stats()
    context = RequestContext(request_id="cli-stats-refresh")
    return use_case.execute(context)


def get_stats(
    use_case: GetServiceStatsUseCase, context: Optional[RequestContext] = None
) -> ServiceStatsResponse:
    """
    Retrieve service statistics (may be from cache).

    Args:
        use_case: GetServiceStatsUseCase instance.
        context: Request context; one naming this command is built when
            none is given.

    Returns:
        The service-wide statistics.
    """
    return use_case.execute(context or RequestContext(request_id="cli-stats-show"))
