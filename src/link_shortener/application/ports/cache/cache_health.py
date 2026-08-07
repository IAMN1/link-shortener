from abc import ABC, abstractmethod


class CacheHealth(ABC):
    """
    Interface a cache implements so its state can be reported truthfully.

    The health check used to work this out from the outside, by reaching
    into the cache's private attributes: it called the client's ``ping``
    directly and, when that failed, fell back to asking whether the cache
    believed itself connected. Both answers were wrong in opposite
    directions.

    A failing direct ``ping`` never told the cache anything, so its
    "available" flag stayed set from the last successful operation and the
    fallback confirmed a Redis that was switched off. Once some other
    request did notice the outage and dropped the client, the absence of a
    client was then read as "no cache is configured" -- so a Redis that had
    since recovered was reported as deliberately disabled, indefinitely,
    because nothing on the health path ever tried to reconnect.

    Both readings came from inferring a state instead of asking the
    component that owns it. The two methods below are that component's
    answers.
    """

    @abstractmethod
    def is_configured(self) -> bool:
        """
        Report whether this cache talks to a server at all.

        Distinguishes "the cache is fine" from "there is no cache", which a
        bare health boolean cannot express. The answer describes the
        deployment, not the connection, so it does not change when the
        server goes away.

        Returns:
            ``True`` if a real backend is configured.
        """
        ...

    @abstractmethod
    def ping(self) -> bool:
        """
        Probe the backend and report whether it answered.

        Probes for real rather than reporting a remembered state: a cache
        remembers its last successful operation, so on a quiet service a
        dead backend stayed "ok" indefinitely -- exactly when a health check
        has to be right.

        Implementations must update their own connection state from the
        result, so that a probe both reports the truth and leaves the cache
        agreeing with it.

        Returns:
            ``True`` if the backend answered, or if there is no backend to
            ask -- a cache with nothing to connect to cannot be down.
        """
        ...
