from typing import Any
from link_shortener.application.ports.cache.link_cache import LinkCache


def clear_cache(cache: LinkCache, stats_only: bool = False) -> None:
    """
    Clear the cache (full or only statistics).

    Args:
        cache: Cache implementation (LinkCache interface).
        stats_only: If True, only delete statistics cache.
    """
    if stats_only:
        if hasattr(cache, "delete_stats"):
            cache.delete_stats()
            print("Statistic cache cleared")
        else:
            print("Cache does not support stats-only clearing.")
    else:
        if hasattr(cache, 'clear_all'):
            cache.clear_all()
            print("Full cache cleared.")
        elif hasattr(cache, 'delete_stats'):
            cache.delete_stats()
            print("Full cache clear not supported. Cleared stats only.")
        else:
            print("No clear method available for this cache.")

def get_cache_info(cache: LinkCache) -> dict[str, Any]:
    """
    Retrieve cache information for monitoring.

    Args:
        cache: Cache implementation.

    Returns:
        Dictionary with cache statistics or {"error": message}.
    """
    if hasattr(cache, "get_cache_info"):
        return cache.get_cache_info()
    return {"error": "Cache info not available"}

def check_redis_connection(cache: LinkCache) -> bool:
    """
    Check if the cache is connected to Redis and responsive.

    Args:
        cache: Cache implementation (expected to be RedisLinkCache).

    Returns:
        True if Redis connection is healthy, False otherwise.
    """
    if hasattr(cache, "_ensure_connection"):
        return cache._ensure_connection()
    return False # Not Redis or no connection method