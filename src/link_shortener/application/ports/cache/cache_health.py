from abc import ABC, abstractmethod


class CacheHealth(ABC):
    """
    Interface a cache implements so its state can be reported truthfully.

    Asked of the cache rather than worked out from the outside. A health
    check reaching into a client of its own cannot tell the two failures
    apart: a ``ping`` that fails leaves the cache's own state untouched,
    and a client dropped by some other request reads as "no cache is
    configured" rather than as an outage. The methods below are the
    component's own answers.
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
    def stores_entries(self) -> bool:
        """
        Report whether anything is actually being cached.

        The other half of ``is_configured``, and apart from it because the
        two were read as one question and are not one. A cache with no
        server can still be keeping entries: ``InMemoryLinkCache`` holds
        them in this process, serves them, and goes on serving a link
        another process deleted until its TTL runs out.

        Answering only ``is_configured`` made every report say the same
        thing about two situations that behave differently. Measured on a
        live run: ``/health`` said ``"cache": "disabled"`` while the same
        process logged four ``Redirect cache hit`` lines in the same
        seconds, and the guide's own troubleshooting entry for a stale
        redirect points at a cache the reports called absent.

        Returns:
            ``True`` if entries are kept anywhere -- in a server or in
            this process.
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
