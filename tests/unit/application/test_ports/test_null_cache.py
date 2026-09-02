from link_shortener.infrastructure.cache.null_cache import NullCache
from link_shortener.domain.value_objects.dedup_scope import DedupScope
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.domain.value_objects.url_hash import UrlHash


class TestNullCache:

    def test_all_methods_no_error(self):

        cache = NullCache()
        short_code = ShortCode("abc123")
        url_hash = UrlHash("a"*64)

        # LinkCache
        assert cache.get_by_code(short_code) is None
        assert cache.get_by_hash(url_hash, DedupScope()) is None
        assert cache.get_by_hashes([url_hash], DedupScope()) == {url_hash: None}
        cache.save(None)
        cache.save_many([])
        cache.delete(None)
        cache.delete_redirect(short_code)

        # RedirectCache
        assert cache.get_redirect(short_code) is None
        cache.save_redirect(short_code, "url")

        # StatsCache
        assert cache.get_stats() is None
        cache.save_stats({})
        cache.delete_stats()
