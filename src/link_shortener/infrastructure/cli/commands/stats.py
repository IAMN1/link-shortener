from link_shortener.application import (
    RequestContext, GetServiceStatsUseCase, StatsCache
)


def refresh_stats(
    use_case: GetServiceStatsUseCase, stats_cache: StatsCache
) -> dict:
    """
    Force a fresh retrieval of service statistics and update the cache.

    The cached entry is dropped first. Without that this command was
    ``get_stats`` under another name: the use case answers from the cache on
    a hit, so it printed "STATISTIC REFRESHED IN CACHE" above the same stale
    numbers it had just been given. That mattered because the batch endpoint
    used to leave those numbers stale by up to a whole batch, and this is
    the command an operator would reach for.

    Args:
        use_case: GetServiceStatsUseCase instance.
        stats_cache: Cache holding the service-wide totals.

    Returns:
        Dictionary with total_urls, total_clicks, avg_clicks_per_url, and popular_links.
    """
    stats_cache.delete_stats()
    context = RequestContext(request_id="cli-stats-refresh")
    stats = use_case.execute(context)
    return {
        "total_urls": stats.total_urls,
        "total_clicks": stats.total_clicks,
        "avg_clicks_per_url": stats.avg_clicks_per_url,
        "popular_links": [(link.short_code, link.clicks) for link in stats.popular_links[:5]],
    }

def get_stats(use_case: GetServiceStatsUseCase) -> dict:
    """
    Retrieve service statistics (may be from cache).

    Args:
        use_case: GetServiceStatsUseCase instance.

    Returns:
        Dictionary with total_urls, total_clicks, avg_clicks_per_url,
        and popular_links as (code, clicks, original_url) tuples.
    """
    context = RequestContext(request_id="cli-stats-show")
    stats = use_case.execute(context)
    return {
                "total_urls": stats.total_urls,
        "total_clicks": stats.total_clicks,
        "avg_clicks_per_url": stats.avg_clicks_per_url,
        "popular_links": [
            (link.short_code, link.clicks, link.original_url) 
            for link in stats.popular_links[:5]
        ],
    }
