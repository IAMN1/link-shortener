"""
End-to-end checks on deduplication, guest limits and the expiry field.

Every guest request here carries its own ``REMOTE_ADDR``. The guest quota is
counted per address against a database shared by the whole session, so a test
that shortened from the default address would spend part of everyone else's
allowance.
"""

import uuid

import pytest

from link_shortener.domain import ShortCode
from tests.integration.conftest import (
    auth_headers, csrf_headers, register_and_login
)


def _url():
    """Return a URL nothing else in the session has shortened."""
    return f"https://example.com/{uuid.uuid4().hex}"


def _guest(ip):
    """
    Build the WSGI environment overrides that place a request at an address.

    Args:
        ip: Client address to present.

    Returns:
        Dict for the test client's ``environ_base``.
    """
    return {"REMOTE_ADDR": ip}


def _shorten(client, url, ip=None, token=None, ttl=None):
    """
    Shorten one URL.

    Args:
        client: Flask test client.
        url: URL to shorten.
        ip: Guest address, when the caller is not authenticated.
        token: Access token, when it is.
        ttl: Optional ``ttl_seconds``.

    Returns:
        The response.
    """
    payload = {"url": url}
    if ttl is not None:
        payload["ttl_seconds"] = ttl
    return client.post(
        "/api/v1/shorten",
        json=payload,
        headers=csrf_headers(client, auth_headers(token)),
        environ_base=_guest(ip or "203.0.113.99"),
    )


def _expire(app, code):
    """
    Move a link's expiry into the past, directly in the database.

    Waiting out a real TTL would put a sleep in the suite; the behaviour
    under test is what happens to an already-expired row.

    Args:
        app: The Flask application.
        code: Short code to expire.
    """
    from datetime import datetime, timedelta, timezone

    from link_shortener.infrastructure.database.models.link_model import LinkModel

    with app.app_context():
        with app.container.get_db_manager().session() as session:
            model = (
                session.query(LinkModel).filter_by(short_code=code).first()
            )
            model.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            session.commit()


class TestDeduplicationIsPerCaller:
    """Shortening a URL somebody else shortened must not hand over their link."""

    def test_two_users_get_two_links_for_the_same_url(self, app, client):
        url = _url()
        token_a = register_and_login(client, email=f"a-{uuid.uuid4().hex}@x.io")
        first = _shorten(app.test_client(), url, token=token_a)

        token_b = register_and_login(
            app.test_client(), email=f"b-{uuid.uuid4().hex}@x.io"
        )
        second = _shorten(app.test_client(), url, token=token_b)

        assert first.status_code == 201
        assert second.status_code == 201
        assert second.get_json()["short_code"] != first.get_json()["short_code"]

    def test_the_second_user_owns_what_they_created(self, app, client):
        url = _url()
        client_a = app.test_client()
        token_a = register_and_login(client_a, email=f"c-{uuid.uuid4().hex}@x.io")
        _shorten(client_a, url, token=token_a)

        client_b = app.test_client()
        token_b = register_and_login(client_b, email=f"d-{uuid.uuid4().hex}@x.io")
        created = _shorten(client_b, url, token=token_b).get_json()

        mine = client_b.get(
            "/api/v1/links/mine", headers=auth_headers(token_b)
        ).get_json()
        assert created["short_code"] in [link["short_code"] for link in mine]

    def test_the_same_user_gets_their_own_link_back(self, app):
        url = _url()
        client = app.test_client()
        token = register_and_login(client, email=f"e-{uuid.uuid4().hex}@x.io")

        first = _shorten(client, url, token=token)
        second = _shorten(client, url, token=token)

        assert first.status_code == 201
        assert second.status_code == 200
        assert second.get_json()["short_code"] == first.get_json()["short_code"]

    def test_a_registered_user_does_not_inherit_a_guests_link(self, app):
        url = _url()
        guest_response = _shorten(app.test_client(), url, ip="203.0.113.10")

        client = app.test_client()
        token = register_and_login(client, email=f"f-{uuid.uuid4().hex}@x.io")
        response = _shorten(client, url, token=token)

        assert response.status_code == 201
        assert (
            response.get_json()["short_code"]
            != guest_response.get_json()["short_code"]
        )


class TestAnExpiredLinkDoesNotBlockItsUrl:
    """
    Deduplication must skip expired links.

    Returning one gave the caller a code that answers 410, and since nothing
    creates a replacement while the expired row is still findable, the URL
    could never be shortened again.
    """

    def test_shortening_again_after_expiry_yields_a_new_live_link(self, app):
        url = _url()
        client = app.test_client()
        token = register_and_login(client, email=f"g-{uuid.uuid4().hex}@x.io")

        first = _shorten(client, url, token=token, ttl=3600).get_json()
        _expire(app, first["short_code"])

        second = _shorten(client, url, token=token)

        assert second.status_code == 201
        assert second.get_json()["short_code"] != first["short_code"]

    def test_the_replacement_actually_redirects(self, app):
        url = _url()
        client = app.test_client()
        token = register_and_login(client, email=f"h-{uuid.uuid4().hex}@x.io")

        first = _shorten(client, url, token=token, ttl=3600).get_json()
        _expire(app, first["short_code"])
        second = _shorten(client, url, token=token).get_json()

        assert client.get(f"/{first['short_code']}").status_code == 410
        assert client.get(f"/{second['short_code']}").status_code == 302


class TestExpiryIsReported:
    """
    ``expires_at`` has to reach the client.

    The dashboard renders a column from it, so while the field was withheld
    every link read "never" -- guest links with seven days to live included.
    """

    def test_a_guest_link_reports_its_expiry(self, app):
        body = _shorten(app.test_client(), _url(), ip="203.0.113.11").get_json()

        assert body["expires_at"] is not None

    def test_a_permanent_link_reports_none(self, app):
        client = app.test_client()
        token = register_and_login(client, email=f"i-{uuid.uuid4().hex}@x.io")

        body = _shorten(client, _url(), token=token).get_json()

        assert body["expires_at"] is None

    def test_the_listing_carries_it_too(self, app):
        client = app.test_client()
        token = register_and_login(client, email=f"j-{uuid.uuid4().hex}@x.io")
        created = _shorten(client, _url(), token=token, ttl=3600).get_json()

        mine = client.get(
            "/api/v1/links/mine", headers=auth_headers(token)
        ).get_json()

        entry = next(
            link for link in mine if link["short_code"] == created["short_code"]
        )
        assert entry["expires_at"] is not None


class TestAPoisonedUrlCannotOccupyACleanOne:
    """
    A URL carrying a newline used to be accepted, stored raw, and then hash
    identically to the clean URL -- normalisation drops the fragment. The
    clean URL then deduplicated onto it and could no longer be shortened
    into anything that works: its redirect raises for good, because a
    ``Location`` header cannot hold a newline.
    """

    def test_a_url_with_a_newline_is_refused(self, app):
        client = app.test_client()

        response = _shorten(client, f"{_url()}#\n", ip="203.0.113.40")

        assert response.status_code == 400

    def test_a_url_with_a_nul_is_refused(self, app):
        client = app.test_client()

        response = _shorten(client, f"{_url()}?a=\x00", ip="203.0.113.41")

        assert response.status_code == 400

    def test_the_clean_url_still_shortens_and_redirects(self, app):
        client = app.test_client()
        url = _url()

        _shorten(client, f"{url}#\n", ip="203.0.113.42")
        created = _shorten(client, url, ip="203.0.113.42")

        assert created.status_code == 201
        assert client.get(f"/{created.get_json()['short_code']}").status_code == 302

    def test_one_poisoned_url_does_not_take_the_batch_down(self, app):
        client = app.test_client()
        good = _url()

        body = client.post(
            "/api/v1/batch/shorten",
            json={"urls": [good, f"{_url()}?a=\x00"]},
            headers=csrf_headers(client),
            environ_base=_guest("203.0.113.43"),
        ).get_json()

        results = {item["url"]: item for item in body["results"]}
        assert results[good]["success"], "a valid URL was lost with the bad one"
        assert not any(
            item["success"] for url, item in results.items() if url != good
        )


class TestBatchObeysTheGuestRules:
    """
    A batch is not a way around what a single request has to obey.

    Without the quota, the default expiry and the guest identifier, a guest
    with nothing left of their allowance could create a batch of permanent
    links that counted as nobody's.
    """

    def test_a_guest_batch_stops_at_the_quota(self, app):
        client = app.test_client()
        # Sized from the quota rather than written as a number. The 13 that
        # stood here was three past an allowance of ten, and it stopped
        # being three past anything the moment the allowance moved: at 20 a
        # batch of 13 fits whole, so there is no overflow left to refuse.
        # That much the test does notice -- it reddens on ``13 == 20``
        # rather than passing -- but what it reports is a number it was
        # never asked about, and the repair anyone reaches for is to write
        # the new number in beside the old one.
        limit = app.config["GUEST_LINK_LIMIT"]
        urls = [_url() for _ in range(limit + 3)]
        # Stated, not left to the reader of the arithmetic above: a batch
        # sized at the allowance overflows by nothing, and then every
        # assertion below holds by being asked about an empty set. Sizing
        # the batch from the quota is what keeps this test alive when the
        # quota moves -- it is not an invitation to size it *at* the quota.
        assert len(urls) > limit

        body = client.post(
            "/api/v1/batch/shorten",
            json={"urls": urls},
            headers=csrf_headers(client),
            environ_base=_guest("203.0.113.20"),
        ).get_json()

        assert body["successful"] == limit
        assert body["failed"] == len(urls) - limit
        assert body["failed"] > 0

    def test_what_did_not_fit_comes_back_per_item(self, app):
        client = app.test_client()
        limit = app.config["GUEST_LINK_LIMIT"]
        urls = [_url() for _ in range(limit + 2)]
        assert len(urls) > limit  # see the note in the test above

        body = client.post(
            "/api/v1/batch/shorten",
            json={"urls": urls},
            headers=csrf_headers(client),
            environ_base=_guest("203.0.113.21"),
        ).get_json()

        refused = [item for item in body["results"] if not item["success"]]
        # Counted, not merely non-empty: "at least one was refused" is
        # satisfied by a batch that refused the wrong number of them.
        assert len(refused) == len(urls) - limit
        assert all("limit" in item["error"].lower() for item in refused)

    def test_links_the_guest_already_has_cost_nothing(self, app):
        """Being handed an existing link is not a creation, so it is free.

        The rule is written beside the code that applies it -- "Only links
        that have to be created draw on the quota; being handed one that
        already exists costs nothing" -- and nothing was holding it:
        measured, charging for them as well (``- len(fetched_results)``)
        left all 708 integration tests passing, and a guest who resubmitted
        their own links was refused links they had allowance for.

        Sized so that the difference shows: the batch fills the allowance
        exactly, and only the free half keeps it from overflowing.
        """
        address = "203.0.113.24"
        client = app.test_client()
        limit = app.config["GUEST_LINK_LIMIT"]

        already_have = [_url() for _ in range(limit // 4)]
        for url in already_have:
            assert _shorten(client, url, ip=address).status_code == 201

        fresh = [_url() for _ in range(limit - len(already_have))]
        body = client.post(
            "/api/v1/batch/shorten",
            json={"urls": already_have + fresh},
            headers=csrf_headers(client),
            environ_base=_guest(address),
        ).get_json()

        assert body["successful"] == len(already_have) + len(fresh)
        assert body["failed"] == 0

    def test_batch_links_expire_like_single_guest_links(self, app):
        client = app.test_client()
        url = _url()

        client.post(
            "/api/v1/batch/shorten",
            json={"urls": [url]},
            headers=csrf_headers(client),
            environ_base=_guest("203.0.113.22"),
        )

        body = _shorten(client, url, ip="203.0.113.22").get_json()
        assert body["expires_at"] is not None

    def test_batch_links_count_against_the_next_request(self, app):
        client = app.test_client()
        limit = app.config["GUEST_LINK_LIMIT"]

        client.post(
            "/api/v1/batch/shorten",
            json={"urls": [_url() for _ in range(limit)]},
            headers=csrf_headers(client),
            environ_base=_guest("203.0.113.23"),
        )

        response = _shorten(client, _url(), ip="203.0.113.23")
        assert response.status_code == 429

    def test_a_url_someone_else_shortened_does_not_fail_the_batch(self, app):
        """
        Per-owner deduplication made an old "cannot happen" branch reachable.

        The other owner's link is not returned, so a new one is created --
        for a URL whose deterministic code is already taken. Reusing that
        code raised IntegrityError on save and lost the whole batch.
        """
        url = _url()
        owner = app.test_client()
        token = register_and_login(owner, email=f"k-{uuid.uuid4().hex}@x.io")
        _shorten(owner, url, token=token)

        client = app.test_client()
        response = client.post(
            "/api/v1/batch/shorten",
            json={"urls": [url]},
            headers=csrf_headers(client),
            environ_base=_guest("203.0.113.25"),
        )

        assert response.status_code == 200
        item = response.get_json()["results"][0]
        assert item["success"], item.get("error")
        assert client.get(f"/{item['short_code']}").status_code == 302

    def test_an_empty_batch_is_answered_not_crashed(self, app):
        """
        The HTTP schema refuses an empty list, so this goes at the layer
        below it: the aggregate's own empty value used to raise
        ``TypeError`` because its ``created_at`` default was a timestamp
        where a factory belonged.
        """
        from link_shortener.application.context import RequestContext

        with app.app_context():
            use_case = app.container.get_batch_create_links_use_case()
            result = use_case.execute([], RequestContext(request_id="batch-0"))

        assert result.total == 0
        assert result.items == []
