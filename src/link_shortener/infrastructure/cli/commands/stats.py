from link_shortener.application.context import RequestContext
from link_shortener.application.use_cases.get_service_stats import GetServiceStatsUseCase


def refresh_stats(use_case: GetServiceStatsUseCase) -> dict:
    """
    Force a fresh retrieval of service statistics and update the cache.

    Args:
        use_case: GetServiceStatsUseCase instance.

    Returns:
        Dictionary with total_urls, total_clicks, avg_clicks_per_url, and popular_links.
    """
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