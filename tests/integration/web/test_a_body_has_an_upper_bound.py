"""How much an anonymous caller may send before the service stops reading.

Nothing bounded it. Flask leaves ``MAX_CONTENT_LENGTH`` unset by default,
there is no proxy in front -- the image runs gunicorn directly -- and
``request.get_json()`` reads the whole body into memory **before** any
validation runs. So the size of an unauthenticated request was decided by
the client.

Measured on the production profile before the setting existed: one
anonymous ``POST /api/v1/shorten`` carrying 60 MB was accepted whole
(62 914 590 bytes uploaded) and only then answered ``400``; four concurrent
200 MB bodies took the container from 342 MiB to 1.598 GiB and 356 % CPU.
The per-endpoint throttle is no help against that -- it counts requests,
and four are enough to hold four synchronous workers.

What is held here is that the limit exists, that it is Flask's own (so it
applies before a view runs), and that the answer is the service's envelope
rather than Werkzeug's HTML.
"""

import json

import pytest


def a_body_of(size: int) -> bytes:
    """
    A syntactically valid shorten request of roughly this many bytes.

    Args:
        size: Wanted length in bytes.

    Returns:
        The encoded JSON body.
    """
    padding = max(0, size - 40)
    return json.dumps({"url": "https://example.com/" + "a" * padding}).encode()


class TestTheLimitIsInPlace:
    """The setting reaches Flask, which is what makes it early."""

    def test_the_application_carries_it(self, client):
        """Read by Werkzeug before the body is consumed.

        Asserted on the application rather than only through a response,
        because *where* the refusal happens is the whole value: a check
        inside a view would refuse after the bytes were already in memory.
        """
        assert client.application.config["MAX_CONTENT_LENGTH"] > 0

    def test_it_holds_the_largest_documented_batch(self, client):
        """A limit that refuses a request the document allows is a bug.

        The same relation ``validate()`` refuses to start on; checked here
        against the configuration that actually assembled.
        """
        config = client.application.config
        largest = config["BATCH_CREATE_LIMIT"] * config["MAX_URL_LENGTH"]

        assert config["MAX_CONTENT_LENGTH"] >= largest


class TestAnOversizedBodyIsRefused:
    """What a caller meets past the limit."""

    def test_it_answers_413(self, client):
        """Not 400: the request was well formed and simply too large."""
        limit = client.application.config["MAX_CONTENT_LENGTH"]

        answer = client.post(
            "/api/v1/shorten",
            data=a_body_of(limit + 1024),
            content_type="application/json",
        )

        assert answer.status_code == 413

    def test_the_answer_is_the_services_own_envelope(self, client):
        """A caller parsing JSON must not meet Werkzeug's HTML page."""
        limit = client.application.config["MAX_CONTENT_LENGTH"]

        answer = client.post(
            "/api/v1/shorten",
            data=a_body_of(limit + 1024),
            content_type="application/json",
        )

        assert answer.is_json
        assert "error" in answer.get_json()

    def test_no_account_is_needed_to_meet_it(self, client):
        """The refusal has to reach the caller the limit exists for.

        The measured exhaustion was anonymous. A limit that only applied
        to signed-in callers would protect the wrong side.
        """
        limit = client.application.config["MAX_CONTENT_LENGTH"]

        answer = client.post(
            "/api/v1/shorten",
            data=a_body_of(limit + 1024),
            content_type="application/json",
        )

        assert answer.status_code == 413


class TestAnOrdinaryBodyIsUnaffected:
    """The limit must not be felt by the requests the service is for."""

    def test_a_normal_shorten_still_works(self, client):
        """One address is four orders of magnitude under the limit."""
        answer = client.post(
            "/api/v1/shorten",
            json={"url": "https://example.com/an-ordinary-address"},
        )

        assert answer.status_code in (200, 201), answer.get_data(as_text=True)

    @pytest.mark.parametrize("size", [4096, 64 * 1024])
    def test_a_body_under_the_limit_is_read(self, client, size):
        """Refused for its content, which means it was read.

        Both sizes are under ``MAX_CONTENT_LENGTH`` and both carry an
        address past ``MAX_URL_LENGTH``, so a 400 here is the validator
        speaking -- which is only reachable if the body was accepted
        first. A 413 would mean the body limit had crept down onto
        requests it is not for.
        """
        answer = client.post(
            "/api/v1/shorten",
            data=a_body_of(size),
            content_type="application/json",
        )

        assert answer.status_code == 400
