"""
Service totals stop being true the moment a link is created or deleted.

Both paths drop the statistics key. Left to a CLI command alone,
``GET /api/v1/stats`` goes on reporting the old count for the whole
``CACHE_STATS_TTL`` -- five minutes in production -- answering 200 with no
sign that it is reading a snapshot: two links reported while the database
holds seven.

Click totals are a different matter and deliberately still lag: they change
on every redirect, and dropping the key each time would leave the cache
with nothing to serve. That is what the TTL is for.

Run against a real cache. With ``CACHE_ENABLED=False``, which the rest of
the integration suite uses, none of this is observable.
"""

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.web.app_factory import create_app
from tests.integration.conftest import IntegrationTestConfig


class CachedIntegrationConfig(IntegrationTestConfig):
    """The shared integration config, with the cache switched on."""
    CACHE_ENABLED = True
    REDIS_ENABLED = False
    DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="module")
def cached_app():
    """An app whose container holds a real in-memory cache."""
    application = create_app(config=CachedIntegrationConfig())
    application.config["TESTING"] = True

    with application.app_context():
        db_manager = application.container.get_db_manager()
        db_manager.create_tables()
        from link_shortener.infrastructure.database.seed import seed_base_roles
        with db_manager.session() as session:
            seed_base_roles(session)

    yield application

    with application.app_context():
        application.container.close()


@pytest.fixture()
def cache(cached_app):
    """The cache the wired-up use cases actually use."""
    with cached_app.app_context():
        return cached_app.container.get_cache()


@pytest.fixture()
def context():
    """An anonymous request context."""
    return RequestContext(request_id="stats-invalidation")


def _warm_stats(cached_app, context):
    """Compute and cache the service statistics."""
    with cached_app.app_context():
        use_case = cached_app.container.get_get_service_stats_use_case()
        return use_case.execute(context)


def _create(cached_app, url, context):
    """Create a link through the real use case."""
    with cached_app.app_context():
        return cached_app.container.get_create_short_link_use_case().execute(
            url, context
        )


class TestTotalsDoNotSurviveTheChangeTheyDescribe:
    """Creation and deletion drop the key the totals live in."""

    def test_creating_a_link_drops_the_cached_totals(
        self, cached_app, cache, context
    ):
        _warm_stats(cached_app, context)
        assert cache.get_stats() is not None

        _create(cached_app, "https://example.com/stats-invalidation-1", context)

        assert cache.get_stats() is None

    def test_deleting_a_link_drops_the_cached_totals(
        self, cached_app, cache, context
    ):
        created = _create(
            cached_app, "https://example.com/stats-invalidation-2", context
        )
        _warm_stats(cached_app, context)
        assert cache.get_stats() is not None

        with cached_app.app_context():
            cached_app.container.get_delete_link_use_case().execute(
                created.short_code, context, enforce_ownership=False
            )

        assert cache.get_stats() is None

    def test_the_next_read_reports_the_new_total(
        self, cached_app, cache, context
    ):
        """The point of dropping the key, stated as the caller sees it."""
        before = _warm_stats(cached_app, context).total_urls

        _create(cached_app, "https://example.com/stats-invalidation-3", context)
        after = _warm_stats(cached_app, context).total_urls

        assert after == before + 1


class TestAFailureIsNotAnEmptyService:
    """
    "I could not count" and "there is nothing to count" are different
    answers, and only one of them was being given.
    """

    def test_a_failing_query_does_not_report_an_empty_service(
        self, cached_app, cache, context
    ):
        """
        Reachable without touching anything: ``DATABASE_STATEMENT_TIMEOUT``
        aborts the aggregate over a large enough table, and answering 200
        with zeros would be a lie the caller cannot detect.
        """
        _create(cached_app, "https://example.com/stats-not-empty", context)

        with cached_app.app_context():
            use_case = cached_app.container.get_get_service_stats_use_case()

            def exploding_uow(*args, **kwargs):
                raise RuntimeError("statement timeout")

            original = use_case.uow_factory
            use_case.uow_factory = exploding_uow
            try:
                # `match` pins which RuntimeError. Without it the test also
                # passes when the failure is caught and re-raised as some
                # other RuntimeError, and when an unrelated one is raised
                # earlier, before the injected factory is reached at all.
                # Both measured. Note what it does not close: `match` is a
                # search, so a wrapper that keeps the original text inside
                # a longer message still passes.
                with pytest.raises(RuntimeError, match="statement timeout"):
                    use_case.execute(context)
            finally:
                use_case.uow_factory = original


class TestClicksStillLagOnPurpose:
    """The counter that changes on every redirect does not drop the key."""

    def test_recording_a_click_leaves_the_cached_totals_alone(
        self, cached_app, cache, context
    ):
        created = _create(
            cached_app, "https://example.com/stats-invalidation-4", context
        )
        _warm_stats(cached_app, context)
        assert cache.get_stats() is not None

        with cached_app.app_context():
            cached_app.container.get_update_link_stats_use_case().execute(
                created.short_code, context
            )

        # Still there. Dropping it here would mean recomputing the totals
        # once per redirect, which is the cost the cache exists to avoid.
        assert cache.get_stats() is not None


class TestTheCachedAnswerIsTheSameAnswer:
    """
    The cache-hit branch rebuilds the response from serialised data.

    Every field crosses the cache as text and comes back as an object --
    ``created_at`` through ``fromisoformat``, the popular links through a
    list rebuilt item by item. Nothing exercised that branch: every test
    above reads the totals once, or drops the key between two reads, so
    the code that runs on the second read in production ran nowhere here.
    """

    def test_the_second_read_is_answered_without_the_database(
        self, cached_app, cache, context
    ):
        """
        Proven by taking the database away.

        A repository that raises is the only way to tell "served from the
        cache" from "computed again and happened to agree": the second
        answer arrives with no unit of work to compute it from.
        """
        created = _create(
            cached_app, "https://example.com/stats-cache-hit-1", context
        )
        with cached_app.app_context():
            cached_app.container.get_update_link_stats_use_case().execute(
                created.short_code, context
            )
        first = _warm_stats(cached_app, context)
        assert cache.get_stats() is not None

        with cached_app.app_context():
            use_case = cached_app.container.get_get_service_stats_use_case()
            original = use_case.uow_factory

            def exploding_uow(*args, **kwargs):
                raise AssertionError("the cached answer went to the database")

            use_case.uow_factory = exploding_uow
            try:
                second = use_case.execute(context)
            finally:
                use_case.uow_factory = original

        assert second.total_urls == first.total_urls
        assert second.total_clicks == first.total_clicks
        assert second.avg_clicks_per_url == first.avg_clicks_per_url

    def test_a_popular_link_survives_the_round_trip_whole(
        self, cached_app, cache, context
    ):
        """
        Item by item, because the list is rebuilt that way.

        A link with a click on it, so the list is not empty: an assertion
        about every item of an empty list is true whatever the branch does
        with it, and this list is empty until something is clicked.
        """
        created = _create(
            cached_app, "https://example.com/stats-cache-hit-2", context
        )
        with cached_app.app_context():
            cached_app.container.get_update_link_stats_use_case().execute(
                created.short_code, context
            )
        first = _warm_stats(cached_app, context)
        assert first.popular_links, "nothing was clicked, so nothing is popular"

        second = _warm_stats(cached_app, context)

        assert [item.short_code for item in second.popular_links] == [
            item.short_code for item in first.popular_links
        ]
        assert [item.short_url for item in second.popular_links] == [
            item.short_url for item in first.popular_links
        ]
        assert [item.original_url for item in second.popular_links] == [
            item.original_url for item in first.popular_links
        ]
        assert [item.clicks for item in second.popular_links] == [
            item.clicks for item in first.popular_links
        ]
        # The moment is the field the cache cannot carry as it stands: it
        # is written as text and read back through `fromisoformat`, and a
        # branch that dropped the timezone would still answer 200.
        assert [item.created_at for item in second.popular_links] == [
            item.created_at for item in first.popular_links
        ]
