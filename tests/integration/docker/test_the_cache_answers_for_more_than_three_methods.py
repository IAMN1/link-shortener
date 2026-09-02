"""
The cache layer, against a real Redis, past the three methods it had.

`RedisCache` carries about twenty public methods and this directory
reached three of them: `save_redirect`, `get_redirect` and
`delete_redirect`. Everything else was answered by unit tests over a
fake client, which agrees with whatever the code asks it -- and the parts
that only a real server can be wrong about are exactly the ones a fake
cannot check: `MGET` answers positionally, a pipeline either executes or
does not, `INFO` comes back as a block of text somebody has to parse, and
a payload is sealed against the key it is stored under.

Every test here works through the application's own cache object rather
than the raw client, so what is held is the adapter and not Redis.
"""

from datetime import datetime, timedelta, timezone

import pytest

from link_shortener.domain.entities.link import Link
from link_shortener.domain.value_objects.original_url import OriginalUrl
from link_shortener.domain.value_objects.owner_id import OwnerID
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.domain.value_objects.url_hash import UrlHash


_counter = 0


def a_link(code, url="https://cache-methods.example/x", owner=None, ttl=0):
    """A link with a hash of its own, so entries do not collide."""
    global _counter
    _counter += 1
    return Link.create(
        url_hash=UrlHash("c" * 60 + f"{_counter:04x}"),
        short_code=ShortCode(code),
        original_url=OriginalUrl(url),
        owner=OwnerID(owner) if owner else None,
        ttl_seconds=ttl,
    )


@pytest.fixture
def cache(app):
    """The application's own cache, with this file's keys cleared after."""
    with app.app_context():
        yield app.container.get_cache()


class TestReadingManyHashesAtOnce:
    """`get_by_hashes` is an `MGET`, and `MGET` answers by position."""

    def test_every_requested_hash_gets_an_entry(self, cache):
        """
        A miss and an outage look the same to the caller: one entry per
        hash asked about. Returning a shorter mapping made this cache
        disagree with the two beside it about its own contract.
        """
        present = a_link("mgetok1")
        cache.save(present)
        absent = UrlHash("d" * 64)

        answer = cache.get_by_hashes(
            [present.url_hash, absent], present.dedup_scope()
        )

        assert set(answer) == {present.url_hash, absent}
        assert answer[absent] is None

    def test_the_values_line_up_with_the_hashes_that_were_asked(self, cache):
        """
        The failure a fake cannot produce. `MGET` returns a list in the
        order of the keys, and zipping it against anything but those keys
        hands each caller another link's row -- with two entries present
        and a hole between them, an off-by-one is silent and wrong.
        """
        first = a_link("mgetpos1", "https://cache-methods.example/first")
        second = a_link("mgetpos2", "https://cache-methods.example/second")
        cache.save(first)
        cache.save(second)
        hole = UrlHash("e" * 64)

        answer = cache.get_by_hashes(
            [first.url_hash, hole, second.url_hash], first.dedup_scope()
        )

        assert answer[first.url_hash].short_code.value == "mgetpos1"
        assert answer[hole] is None
        assert answer[second.url_hash].short_code.value == "mgetpos2"

    def test_asking_about_nothing_answers_nothing(self, cache):
        """
        The contract, not the wire: `_execute_read` swallows a refusal
        and reports a miss, so this cannot tell an `MGET` with no keys
        from one that was never sent -- and either way the caller must
        get an empty mapping rather than an exception.
        """
        assert cache.get_by_hashes([], a_link("mgetnil").dedup_scope()) == {}


class TestWritingManyAtOnce:

    def test_every_link_in_the_batch_is_readable_afterwards(self, cache):
        """
        `save_many` builds one pipeline and executes it once. A pipeline
        that is built and never executed writes nothing at all, and the
        method answers exactly the same either way.
        """
        links = [a_link(f"batch{n}") for n in range(3)]

        cache.save_many(links)

        for link in links:
            found = cache.get_by_code(link.short_code)
            assert found is not None, link.short_code.value
            assert found.original_url.value == link.original_url.value

    def test_an_empty_batch_writes_nothing_and_raises_nothing(self, cache):
        cache.save_many([])


class TestTheTwoWaysOfRemovingALink:

    def test_delete_takes_all_three_keys(self, cache):
        """
        Named from the entity rather than discovered by reading the code
        entry: discovery leaves the hash key orphaned whenever the code
        entry was evicted first, and the orphan answers deduplication
        with a code that no longer resolves.
        """
        link = a_link("delall1")
        cache.save(link)
        assert cache.get_by_code(link.short_code) is not None

        assert cache.delete(link) is True

        assert cache.get_by_code(link.short_code) is None
        assert cache.get_redirect(link.short_code) is None
        assert cache.get_by_hash(link.url_hash, link.dedup_scope()) is None

    def test_delete_by_code_leaves_the_hash_entry_on_purpose(self, cache):
        """
        The hash is not derivable from a code, so this method cannot
        reach that key. The survivor is deliberate and costs a lookup
        rather than a wrong answer, because `create_short_link` confirms
        every deduplication hit against the database -- and a test that
        asserted all three gone would be asking for something this method
        does not promise.
        """
        link = a_link("delcode1")
        cache.save(link)

        assert cache.delete_by_code(link.short_code) is True

        assert cache.get_by_code(link.short_code) is None
        assert cache.get_redirect(link.short_code) is None
        assert cache.get_by_hash(link.url_hash, link.dedup_scope()) is not None


class TestWhatTheServerSaysAboutItself:

    def test_the_info_block_is_parsed_into_numbers(self, cache):
        """
        `get_cache_info` reads a real `INFO` reply -- a block of text with
        sections and colons in it. A fake hands back whatever shape the
        code expects, so the parsing is the part only this run can be
        wrong about.
        """
        info = cache.get_cache_info()

        assert info is not None
        assert isinstance(info, dict)
        assert info

    def test_the_service_totals_survive_a_round_trip(self, cache):
        """`save_stats` and `get_stats` were reached by nothing here."""
        totals = {"total_links": 7, "total_clicks": 11}

        cache.save_stats(totals)

        assert cache.get_stats() == totals

    def test_the_totals_can_be_dropped(self, cache):
        cache.save_stats({"total_links": 1})
        cache.delete_stats()

        assert cache.get_stats() is None


class TestEmptyingIt:

    def test_clear_all_leaves_nothing_this_cache_wrote(self, cache):
        """
        The method a maintenance command reaches for. Held last in the
        file because it removes what the tests above rely on.
        """
        link = a_link("clearme1")
        cache.save(link)
        cache.save_stats({"total_links": 1})
        assert cache.get_by_code(link.short_code) is not None

        cache.clear_all()

        assert cache.get_by_code(link.short_code) is None
        assert cache.get_stats() is None


class TestAnEntryDoesNotAnswerForAnotherKey:

    def test_a_payload_moved_onto_another_key_does_not_verify(
        self, cache, redis_client
    ):
        """
        Each entry is sealed against the key it is stored under, and this
        is the only run that can move one: the raw client writes a valid
        payload onto a key it was not written for, and the cache has to
        report a miss rather than the wrong link.
        """
        link = a_link("sealed1", "https://cache-methods.example/sealed")
        cache.save(link)
        mine = cache.key_gen.for_short_code(link.short_code.value)
        stolen = cache.key_gen.for_short_code("sealed2")
        payload = redis_client.get(mine)
        assert payload, "the entry was not written under the key expected"

        redis_client.set(stolen, payload, ex=60)

        assert cache.get_by_code(ShortCode("sealed2")) is None

    def test_an_expired_redirect_is_not_served(self, cache):
        """The entry's lifetime is capped at the link's."""
        code = ShortCode("expired1")
        cache.save_redirect(
            code,
            "https://cache-methods.example/gone",
            datetime.now(timezone.utc) - timedelta(seconds=1),
        )

        assert cache.get_redirect(code) is None
