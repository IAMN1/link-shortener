"""
What a delete performed elsewhere leaves the serving process answering.

``docs/architecture.md`` lists invalidation as a table: deleting a link
drops every key of that link. That is true of one process. With
``REDIS_ENABLED=false`` each process holds its own copy of both cache
levels, so an invalidation reaches the process that performed it and no
other — the CLI included, which is a separate process by definition.

Measured on the arrangement the local profile ships, before this was
written: a link created and followed over HTTP, then ``flask link delete``
in a terminal. The command answered ``Link '<code>' has been deleted``,
``GET /api/v1/links/<code>`` answered ``404`` -- and ``GET /<code>`` went
on answering ``302`` to the original destination three times running, out
of the server's own ``RedirectCache``, for up to ``CACHE_LINK_TTL``.

Two applications on one database file, because that is what the situation
is: one store, two caches, and a deletion performed in only one of them.
The second application stands for the CLI.

The remedy the warning offers is checked too. A caveat that names a way
out is worth no more than the way out, and ``CACHE_ENABLED=false`` is the
one this can hold: the redirect then reads the row every time and the
delete is seen at once.
"""

import pytest

from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.infrastructure.database.seed import seed_base_roles
from link_shortener.web.app_factory import create_app


URL = "https://example.com/deleted-in-another-process"


def _app(tmp_path, name, cache_enabled, create_tables):
    """An application on the shared database file."""
    class Config(TestingConfig):
        pass

    Config.CACHE_ENABLED = cache_enabled
    Config.REDIS_ENABLED = False
    Config.MAIL_ENABLED = False
    Config.DATABASE_URL = f"sqlite:///{tmp_path}/{name}.db"

    app = create_app(config=Config())
    if create_tables:
        with app.app_context():
            manager = app.container.get_db_manager()
            manager.create_tables()
            with manager.session() as session:
                seed_base_roles(session)
    return app


def _make_and_follow(app):
    """Create a link and follow it once, so the redirect cache holds it."""
    with app.test_client() as client:
        made = client.post("/api/v1/shorten", json={"url": URL})
        assert made.status_code == 201, made.get_data(as_text=True)[:200]
        code = made.get_json()["short_code"]
        assert client.get(f"/{code}").status_code == 302
    return code


def _delete_elsewhere(app, code):
    """Delete the link through a second application's own container."""
    with app.app_context():
        from link_shortener.application import RequestContext

        use_case = app.container.get_delete_link_use_case()
        deleted = use_case.execute(
            code,
            RequestContext(request_id="another-process"),
            enforce_ownership=False,
        )
    assert deleted, "the second application did not delete the link"


class TestWithTheCacheInTheProcess:
    """The arrangement the warning is about."""

    @pytest.fixture(scope="class")
    def after_the_delete(self, tmp_path_factory):
        tmp_path = tmp_path_factory.mktemp("cross-process-delete")
        serving = _app(tmp_path, "shared", True, create_tables=True)
        code = _make_and_follow(serving)

        elsewhere = _app(tmp_path, "shared", True, create_tables=False)
        _delete_elsewhere(elsewhere, code)
        return serving, code

    def test_the_row_is_gone(self, after_the_delete):
        """The delete really happened; the rest is about the cache."""
        serving, code = after_the_delete

        with serving.test_client() as client:
            assert client.get(f"/api/v1/links/{code}").status_code == 404

    def test_the_first_redirect_after_it_still_answers(self, after_the_delete):
        """
        One stale redirect, and it is unavoidable.

        The serving process holds the entry and has not been told
        otherwise; nothing about this request reaches the database before
        the answer goes out. That is what the L1 cache is for.
        """
        serving, code = after_the_delete

        with serving.test_client() as client:
            response = client.get(f"/{code}", follow_redirects=False)

        assert response.status_code == 302
        assert response.headers["Location"] == URL

    def test_and_the_next_one_does_not(self, after_the_delete):
        """
        The stale entry lasts one redirect, not an hour.

        Counting the click is the one thing that always asks the database,
        and it now drops the entry when the row is not there to increment.
        Before that, the entry stood for ``CACHE_LINK_TTL`` -- measured on
        a live stack at six minutes and still going, across two
        ``cache clear`` runs in another process.
        """
        serving, code = after_the_delete

        with serving.test_client() as client:
            client.get(f"/{code}", follow_redirects=False)
            second = client.get(f"/{code}", follow_redirects=False)

        assert second.status_code == 404


class TestWithTheCacheTurnedOff:
    """`CACHE_ENABLED=false`, the way out the warning names."""

    @pytest.fixture(scope="class")
    def after_the_delete(self, tmp_path_factory):
        tmp_path = tmp_path_factory.mktemp("cross-process-delete-nocache")
        serving = _app(tmp_path, "nocache", False, create_tables=True)
        code = _make_and_follow(serving)

        elsewhere = _app(tmp_path, "nocache", False, create_tables=False)
        _delete_elsewhere(elsewhere, code)
        return serving, code

    def test_the_redirect_stops_at_once(self, after_the_delete):
        serving, code = after_the_delete

        with serving.test_client() as client:
            assert client.get(f"/{code}").status_code == 404
