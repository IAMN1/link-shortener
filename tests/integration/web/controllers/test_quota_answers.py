"""
Tests that a refusal says which limit refused it, and when to come back.

There are two limits and they are nothing alike: the rate limiter counts
requests per minute, the guest quota counts links per day. Both answer 429.

Carrying the rate limiter's headers on the quota's answer -- a body saying
"limit of 10 exceeded" next to ``X-RateLimit-Remaining: 19`` -- and no
``Retry-After`` at all leaves a client unable to tell "wait a minute" from
"come back tomorrow". And the same refusal on the batch endpoint answered
200, so which status the caller saw depended on which endpoint they asked.

A batch that spends the allowance partway down the list still answers 200,
because some of it was created, and a header describes the whole response.
So the per-item refusal carries the window itself: without it, the half of
a batch the quota turned away was the one refusal in the service that never
said when it clears.
"""

import itertools
import uuid

import pytest

from tests.integration.conftest import csrf_headers


_addresses = itertools.count(1)


def _url():
    return f"https://example.com/{uuid.uuid4().hex}"


@pytest.fixture()
def guest_address():
    """One address per test: the quota and the throttle both count by it."""
    number = next(_addresses)
    return f"198.19.{number // 256 % 256}.{number % 256}"


def _shorten(client, address, url=None):
    return client.post(
        "/api/v1/shorten",
        json={"url": url or _url()},
        headers=csrf_headers(client),
        environ_base={"REMOTE_ADDR": address},
    )


def _batch(client, address, urls):
    return client.post(
        "/api/v1/batch/shorten",
        json={"urls": urls},
        headers=csrf_headers(client),
        environ_base={"REMOTE_ADDR": address},
    )


def _spend_the_quota(client, address, app):
    """Create links until the guest allowance is gone."""
    limit = app.config["GUEST_LINK_LIMIT"]
    for _ in range(limit):
        assert _shorten(client, address).status_code == 201


class TestTheQuotaRefusalSpeaksForItself:

    def test_it_answers_429(self, client, app, guest_address):
        _spend_the_quota(client, guest_address, app)

        response = _shorten(client, guest_address)

        assert response.status_code == 429

    def test_it_says_when_to_come_back(self, client, app, guest_address):
        _spend_the_quota(client, guest_address, app)

        response = _shorten(client, guest_address)

        window = app.config["GUEST_LINK_WINDOW_DAYS"] * 24 * 3600
        assert response.headers["Retry-After"] == str(window)

    def test_it_does_not_carry_the_throttles_counters(
        self, client, app, guest_address
    ):
        """
        They describe a different limit, and next to this body they said
        the opposite of it.
        """
        _spend_the_quota(client, guest_address, app)

        response = _shorten(client, guest_address)

        assert "X-RateLimit-Remaining" not in response.headers

    def test_an_ordinary_answer_still_carries_them(
        self, client, guest_address
    ):
        response = _shorten(client, guest_address)

        assert response.status_code == 201
        assert "X-RateLimit-Remaining" in response.headers


class TestTheBatchAnswersTheSameWay:

    def test_a_batch_the_quota_refuses_entirely_answers_429(
        self, client, app, guest_address
    ):
        _spend_the_quota(client, guest_address, app)

        response = _batch(client, guest_address, [_url(), _url()])

        assert response.status_code == 429, response.get_json()
        assert response.headers["Retry-After"]

    def test_a_batch_that_gets_something_done_keeps_its_per_item_errors(
        self, client, app, guest_address
    ):
        """
        Partial success is what the response format exists for: what fits is
        created, what does not comes back as an item error.
        """
        limit = app.config["GUEST_LINK_LIMIT"]
        for _ in range(limit - 1):
            assert _shorten(client, guest_address).status_code == 201

        response = _batch(client, guest_address, [_url(), _url(), _url()])

        assert response.status_code == 200, response.get_json()
        body = response.get_json()
        assert body["failed"] >= 1
        assert body["successful"] >= 1

    def test_a_refused_item_says_when_the_allowance_comes_back(
        self, client, app, guest_address
    ):
        """The window the whole-batch refusal puts in ``Retry-After``.

        The same number, because it is the same refusal: one is raised and
        one is carried, and a caller who reads either has to be told the
        same thing about when to try again.
        """
        limit = app.config["GUEST_LINK_LIMIT"]
        for _ in range(limit - 1):
            assert _shorten(client, guest_address).status_code == 201

        response = _batch(client, guest_address, [_url(), _url(), _url()])

        assert response.status_code == 200, response.get_json()
        refused = [
            item for item in response.get_json()["results"]
            if not item["success"]
        ]
        window = app.config["GUEST_LINK_WINDOW_DAYS"] * 24 * 3600
        assert refused
        assert all(item["error"] == "GUEST_LINK_LIMIT" for item in refused)
        assert all(
            item["retry_after_seconds"] == window for item in refused
        )

    def test_a_refusal_that_does_not_clear_says_nothing_about_waiting(
        self, client, app, guest_address
    ):
        """A malformed URL is not a wait, it is a different URL.

        Filling the field for every refusal would tell a caller to come
        back tomorrow for an address that will still be malformed then.
        """
        response = _batch(client, guest_address, ["not-a-url"])

        item = response.get_json()["results"][0]
        assert item["error"] == "VALIDATION_ERROR"
        assert item["retry_after_seconds"] is None

    def test_a_batch_with_a_malformed_url_still_reports_per_item(
        self, client, app, guest_address
    ):
        """One bad URL is an answer about that URL, not a refusal of the request."""
        _spend_the_quota(client, guest_address, app)

        response = _batch(client, guest_address, ["not-a-url"])

        assert response.status_code == 200, response.get_json()
        assert response.get_json()["failed"] == 1
