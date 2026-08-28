from abc import ABC, abstractmethod
from typing import Any, Dict


class CacheMaintenance(ABC):
    """
    Interface for the two things done *to* a cache rather than with it.

    Neither belongs to the roles beside it: ``LinkCache`` and
    ``RedirectCache`` are how the service reads and writes entries, and
    ``CacheHealth`` answers whether the backend is there. These two are an
    operator's, reached from ``flask cache clear`` and ``flask cache
    stats``, and they were declared by no port at all -- present on the
    Redis and in-memory implementations, absent from the null one.

    What that cost was paid twice. The CLI probed for them with
    ``hasattr`` and carried three branches for what it might find, none of
    which could run; and the end-to-end test that has to empty Redis
    between journeys said in its own comment that it "reaches past
    ``ServiceCache``" to call a method the port did not declare. A
    capability two callers depend on is a capability the port owes them.
    """

    @abstractmethod
    def clear_all(self) -> None:
        """
        Drop every entry this cache holds.

        Everything, not only the statistics: with the database emptied and
        the cache left full, a redirect to a link that no longer exists is
        still answered out of it.
        """
        ...

    @abstractmethod
    def get_cache_info(self) -> Dict[str, Any]:
        """
        Report what the cache holds, for a person reading a terminal.

        The shape is the implementation's own -- a Redis cache counts keys
        and memory, an in-memory one counts entries -- so this is a
        mapping rather than a named type. An implementation that cannot
        answer says so in an ``error`` key rather than raising: the
        command that prints this is a diagnostic, and a diagnostic that
        dies tells the operator less than one that reports the outage.

        Returns:
            Whatever this cache can say about itself.
        """
        ...
