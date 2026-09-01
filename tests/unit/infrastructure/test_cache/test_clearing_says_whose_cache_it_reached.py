"""
"Cache cleared." was true of the process that typed it and of nothing else.

With no cache service configured the entries live in the memory of whichever
process holds them -- the start-up line says so: "Redis is off, using the
in-memory cache; entries are not shared between workers". ``flask cache
clear`` is a process of its own, so it empties a cache nothing was serving
from, and then reports success.

Measured on the arrangement row 5 of the guide's table ships (application on
the host, database in a container, cache in the process), against a running
server:

    GET /<code>                          -> 302 to the original destination
    UPDATE urls SET original_url='…/CHANGED-BY-ME' WHERE short_code=…
    GET /<code>  x2                      -> 302 to the OLD destination
    flask cache clear                    -> "Cache cleared."   exit 0
    GET /<code>  x2                      -> 302 to the OLD destination

Nine such requests over twelve minutes in a longer walk, all stale, with
``CACHE_LINK_TTL=3600``. The operator was told the one thing they came to do
was done.

Held here rather than at the command, because it is the sentence that was
wrong and the sentence is what this module returns.
"""

from unittest.mock import MagicMock

from link_shortener.infrastructure.cli.commands.cache import clear_cache


def a_cache(configured: bool):
    """A cache that either has a service behind it or lives in the process."""
    cache = MagicMock()
    cache.is_configured.return_value = configured
    return cache


class TestACacheThatLivesInThisProcess:
    """``is_configured()`` is False: nothing outside this process was reached."""

    def test_clearing_says_so(self):
        said = clear_cache(a_cache(False))

        assert said.startswith("Cache cleared.")
        assert "In this process only" in said

    def test_it_names_what_to_do_instead(self):
        """
        A sentence that only says "this did nothing for you" leaves the
        operator where they started.
        """
        said = clear_cache(a_cache(False))

        assert "Restart" in said
        assert "CACHE_LINK_TTL" in said

    def test_the_statistics_form_says_it_too(self):
        """Same cache, same reach, and the same thing to know about it."""
        said = clear_cache(a_cache(False), stats_only=True)

        assert said.startswith("Statistics cache cleared.")
        assert "In this process only" in said

    def test_it_still_clears(self):
        """The warning is added to the act, not put in place of it."""
        cache = a_cache(False)

        clear_cache(cache)

        cache.clear_all.assert_called_once()


class TestACacheWithAServiceBehindIt:
    """
    ``is_configured()`` is True: one cache, and everybody sees the clearing.

    This half is what keeps the sentence from being pasted on every answer:
    on rows 1, 2 and 4 of that table the entries are in Redis, the command
    reaches the same entries the server is serving from, and there is
    nothing to warn about.
    """

    def test_clearing_says_nothing_extra(self):
        said = clear_cache(a_cache(True))

        assert said == "Cache cleared."

    def test_neither_does_the_statistics_form(self):
        said = clear_cache(a_cache(True), stats_only=True)

        assert said == "Statistics cache cleared."
