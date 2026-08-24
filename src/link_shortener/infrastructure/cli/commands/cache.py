from typing import Any

from link_shortener.application.ports.cache.service_cache import ServiceCache


def clear_cache(cache: ServiceCache, stats_only: bool = False) -> str:
    """
    Clear the cache, and say what was cleared.

    Asked of the object in the combination it is handed out in, rather
    than probed with ``hasattr`` for each method in turn. The probing was
    not a defence: ``delete_stats`` is abstract on ``StatsCache``, so the
    branch that reported it missing could not run, and the two branches
    below it could not run either. What it did instead was hide that
    ``clear_all`` is declared by no port at all, so the one operation
    this command exists for rested on whichever implementation happened
    to be wired in.

    Args:
        cache: The cache in all five of its roles.
        stats_only: Clear only the statistics entry.

    Returns:
        The line to report, for the adapter to print. Returned rather
        than printed here: what a command says belongs to the layer that
        talks to the terminal, and this module is the one place in it
        that used to print for itself.
    """
    if stats_only:
        cache.delete_stats()
        return "Statistics cache cleared."

    cache.clear_all()
    return "Cache cleared."


def get_cache_info(cache: ServiceCache) -> dict[str, Any]:
    """
    Retrieve cache information for monitoring.

    Args:
        cache: The cache in all five of its roles.

    Returns:
        Whatever the cache reports about itself. A cache with nothing to
        report answers ``{"error": ...}`` of its own accord; that is its
        answer to give, not something guessed at from out here.
    """
    return cache.get_cache_info()


def cache_health(cache: ServiceCache) -> tuple[bool, bool]:
    """
    Ask the cache whether it is configured, and whether it answers.

    Both questions are asked of the cache, which is what ``CacheHealth``
    exists for and what ``/health`` and ``flask maintenance health``
    already do. This command asked neither: it reached for
    ``RedisLinkCache._ensure_connection`` -- a private method of one
    implementation, absent from the other two -- and read the answer as a
    verdict on Redis.

    That method is documented to answer without asking: "A client
    believed to be up is used without probing it first." Measured against
    a cache holding a client whose backend had gone away,
    ``_ensure_connection()`` returned ``True`` while ``ping()`` returned
    ``False`` -- so the command an operator runs precisely to find out
    whether Redis is up printed "Redis connection is healthy." over a
    dead one, in the same second ``maintenance health`` printed "Cache:
    FAILED".

    Whether a cache is expected is asked of the cache as well, rather
    than worked out from ``REDIS_ENABLED`` and ``CACHE_ENABLED``: two
    expressions of one question drift, and this one had already drifted
    from the one ``health`` uses.

    Args:
        cache: The cache in all five of its roles.

    Returns:
        ``(configured, alive)`` -- whether the cache talks to a server at
        all, and whether that server answered just now.
    """
    return cache.is_configured(), cache.ping()
