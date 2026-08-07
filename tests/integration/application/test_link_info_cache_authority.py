"""
What the link-info endpoints do with the cache: nothing, in either
direction.

Two separate reasons, both learned the hard way.

*They do not read it.* A cached entry says a link existed when the entry
was written; it cannot say whether it still does, and that is the whole
question these endpoints answer. An entry that outlived its row was served
as a healthy link, complete with a click count for something the database
no longer had.

*They do not write it.* The write would land after the transaction closes,
where a concurrent ``DELETE`` has already done its invalidating -- so the
entry reappears behind the deletion, and the redirect goes on serving a
link the API reports as gone.

The app here runs with a real cache switched on, because with
``CACHE_ENABLED=False`` -- the setting the rest of the integration suite
uses -- neither behaviour can be observed at all.
"""

import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from link_shortener.application.context import RequestContext
from link_shortener.domain import ShortCode
from link_shortener.web.app_factory import create_app
from tests.integration.conftest import IntegrationTestConfig


class CachedIntegrationConfig(IntegrationTestConfig):
    """Same as the shared integration config, but with the cache alive."""
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
    """The very cache the wired-up use cases would use."""
    with cached_app.app_context():
        return cached_app.container.get_cache()


@pytest.fixture()
def client(cached_app):
    """Fresh, unauthenticated client."""
    return cached_app.test_client()


def _insert(cached_app, code, expires_at=None, clicks=0):
    """Put a row in the database without going through the create path."""
    with cached_app.app_context():
        db = cached_app.container.get_db_manager()
        with db.session() as session:
            session.execute(text(
                "INSERT OR REPLACE INTO urls (id, url_hash, short_code, "
                "original_url, created_at, clicks, expires_at) "
                "VALUES (:id, :hash, :code, :url, :created, :clicks, :expires)"
            ), {
                "id": f"row-{code}",
                "hash": hashlib.sha256(code.encode()).hexdigest(),
                "code": code,
                "url": f"https://example.com/{code}",
                "created": datetime.now(timezone.utc) - timedelta(days=1),
                "clicks": clicks,
                "expires": expires_at,
            })
            session.commit()


def _drop_row(cached_app, code):
    """Remove the row while leaving whatever is in the cache untouched."""
    with cached_app.app_context():
        db = cached_app.container.get_db_manager()
        with db.session() as session:
            session.execute(
                text("DELETE FROM urls WHERE short_code=:c"), {"c": code}
            )
            session.commit()


class TestReadsDoNotWriteTheCache:
    """
    A read must not leave an entry behind.

    An entry written after the reader's transaction closed is exactly the
    one that survives a deletion running alongside it, and it survives for
    ``CACHE_LINK_TTL`` -- an hour, in production.
    """

    def test_basic_info_leaves_no_entry(self, cached_app, client, cache):
        _insert(cached_app, "NOWRT1")

        assert client.get("/api/v1/links/NOWRT1").status_code == 200

        assert cache.get_by_code(ShortCode("NOWRT1")) is None

    def test_extended_info_leaves_no_entry(self, cached_app, client, cache):
        """Including when the request is refused: the lookup still ran."""
        _insert(cached_app, "NOWRT2")

        assert client.get("/api/v1/links/NOWRT2/extended").status_code == 401

        assert cache.get_by_code(ShortCode("NOWRT2")) is None

    # There is deliberately no test here that deletes a row and then reads
    # it: with the row already gone the read raises before it could write
    # anything, so such a test passes with the write put back. The race it
    # would be imitating needs the delete to land *during* the read, which
    # is timing, not sequence. What is testable is the invariant that makes
    # the race unreachable from this path -- a successful read leaves
    # nothing behind -- and that is what the two tests above check.


class TestCountingAClickDoesNotResurrectALink:
    """
    The click counter used to write the cached entity back after its own
    transaction closed. A ``DELETE`` committing in between had already
    invalidated the entry, so the write put it back behind the deletion --
    and the redirect went on serving a link the API answered 404 for, for
    the rest of ``CACHE_LINK_TTL``.

    Reproduced over plain HTTP with no privileges: 24 concurrent readers
    against one delete, about one resurrection in ten. What is asserted
    here is the invariant that takes this path out of the race, because the
    race itself is timing and cannot be written down as a sequence.
    """

    def test_recording_a_click_leaves_no_entry(self, cached_app, client, cache):
        _insert(cached_app, "CLICK1")

        with cached_app.app_context():
            cached_app.container.get_update_link_stats_use_case().execute(
                "CLICK1", RequestContext(request_id="click-no-write")
            )

        assert cache.get_by_code(ShortCode("CLICK1")) is None

    def test_a_late_click_cannot_revive_a_deleted_link(
        self, cached_app, client, cache
    ):
        """
        The shape of the race in slow motion: the row is already gone and
        its entry already dropped when the click task finally runs, exactly
        as a queued task does when a delete overtakes it.
        """
        _insert(cached_app, "CLICK2")
        assert client.get("/CLICK2", follow_redirects=False).status_code == 302
        assert cache.get_by_code(ShortCode("CLICK2")) is not None

        _drop_row(cached_app, "CLICK2")
        cached = cache.get_by_code(ShortCode("CLICK2"))
        if cached is not None:
            cache.delete(cached)
        cache.delete_redirect(ShortCode("CLICK2"))

        with cached_app.app_context():
            cached_app.container.get_update_link_stats_use_case().execute(
                "CLICK2", RequestContext(request_id="late-click")
            )

        assert cache.get_by_code(ShortCode("CLICK2")) is None
        assert client.get("/CLICK2", follow_redirects=False).status_code == 404


class TestReadsDoNotAnswerFromTheCache:
    """The repository decides, whatever the cache is holding."""

    def test_an_entry_without_a_row_is_not_an_answer(
        self, cached_app, client, cache
    ):
        _insert(cached_app, "GHOST1", clicks=99)
        assert client.get("/GHOST1", follow_redirects=False).status_code == 302
        assert cache.get_by_code(ShortCode("GHOST1")) is not None

        # The row disappears behind the cache's back, as it would if
        # invalidation failed or somebody wrote to Redis directly.
        _drop_row(cached_app, "GHOST1")

        assert client.get("/api/v1/links/GHOST1").status_code == 404

    def test_an_entry_cannot_keep_an_expired_link_alive(
        self, cached_app, client, cache
    ):
        _insert(cached_app, "GHOST2")
        assert client.get("/GHOST2", follow_redirects=False).status_code == 302
        assert cache.get_by_code(ShortCode("GHOST2")) is not None

        # Still alive in the cache, already expired in the database.
        _insert(
            cached_app,
            "GHOST2",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

        assert client.get("/api/v1/links/GHOST2").status_code == 410
