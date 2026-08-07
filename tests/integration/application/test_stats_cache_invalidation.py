"""
Service totals stop being true the moment a link is created or deleted.

Nothing used to drop the statistics key except a CLI command, so
``GET /api/v1/stats`` went on reporting the old count for the whole
``CACHE_STATS_TTL`` -- five minutes in production -- answering 200 with no
sign that it was reading a snapshot. Measured before the fix: two links
reported while the database held seven.

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
        aborts the aggregate over a large enough table, and the endpoint
        used to answer 200 with zeros -- a lie the caller cannot detect.
        """
        _create(cached_app, "https://example.com/stats-not-empty", context)

        with cached_app.app_context():
            use_case = cached_app.container.get_get_service_stats_use_case()

            def exploding_uow(*args, **kwargs):
                raise RuntimeError("statement timeout")

            original = use_case.uow_factory
            use_case.uow_factory = exploding_uow
            try:
                with pytest.raises(RuntimeError):
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
