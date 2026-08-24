from link_shortener.application.ports.cache.cache_health import CacheHealth
from link_shortener.application.ports.cache.cache_maintenance import (
    CacheMaintenance,
)
from link_shortener.application.ports.cache.link_cache import LinkCache
from link_shortener.application.ports.cache.link_service_stats_cache import (
    StatsCache,
)
from link_shortener.application.ports.cache.redirect_cache import RedirectCache


class ServiceCache(
    LinkCache, RedirectCache, StatsCache, CacheHealth, CacheMaintenance
):
    """
    The five cache roles one object plays in this service.

    Every implementation -- Redis, in-memory and null -- already inherits all
    five, and the container hands the same instance out for each. Naming the
    combination is what lets a holder say so: typed as ``LinkCache`` alone,
    the attribute understates the object, and passing it where a
    ``StatsCache`` is expected reads as a mistake rather than as the design.

    Nothing new is declared here. A use case that needs one role still asks
    for that role: this exists for the places that hold the object itself.
    """
