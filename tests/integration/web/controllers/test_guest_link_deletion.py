"""
Tests that whoever made a guest link can take it back.

A link created without an account has no owner, so ``link:delete_own`` has
nothing to compare against and can never match: its creator could not delete
it, and only a holder of ``link:delete_any`` could. It sat there until it
expired, seven days by default.

The address it came from is not proof of anything -- it changes, and behind
one NAT it belongs to a crowd -- so what is handed out instead is a signed
token naming that particular link, returned once in the creation response.
It names the row and not the code, because a code freed by deletion can be
issued again.
"""

import itertools
import uuid

import pytest

from tests.integration.conftest import (
    auth_headers, csrf_headers, register_and_login
)


_addresses = itertools.count(1)


def _url():
    return f"https://example.com/{uuid.uuid4().hex}"


def _address():
    number = next(_addresses)
    return f"198.51.{number // 256 % 256}.{number % 256}"


def _create_as_guest(client, url=None):
    """Shorten as an anonymous caller and return the response body."""
    response = client.post(
        "/api/v1/shorten",
        json={"url": url or _url()},
        headers=csrf_headers(client),
        environ_base={"REMOTE_ADDR": _address()},
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def _delete(client, code, token=None, auth=None):
    headers = csrf_headers(client, auth_headers(auth) if auth else None)
    if token:
        headers["X-Deletion-Token"] = token
    return client.delete(f"/api/v1/links/{code}", headers=headers)


class TestTheTokenIsIssuedWhereItIsNeeded:

    def test_a_guest_link_comes_with_one(self, client):
        body = _create_as_guest(client)

        assert body["deletion_token"]

    def test_an_account_link_does_not(self, client, app):
        """An account has ``link:delete_own`` and its links have an owner."""
        token = register_and_login(
            client, email=f"owner-{uuid.uuid4().hex}@example.com"
        )
        response = client.post(
            "/api/v1/shorten",
            json={"url": _url()},
            headers=csrf_headers(client, auth_headers(token)),
        )

        assert response.get_json()["deletion_token"] is None

    def test_reading_the_link_later_never_reveals_it(self, client):
        body = _create_as_guest(client)

        info = client.get(f"/api/v1/links/{body['short_code']}").get_json()

        assert info.get("deletion_token") is None


class TestTheTokenDeletes:

    def test_its_holder_can_delete_the_link(self, client):
        body = _create_as_guest(client)

        response = _delete(client, body["short_code"], token=body["deletion_token"])

        assert response.status_code == 200, response.get_json()
        assert client.get(f"/{body['short_code']}").status_code == 404

    def test_without_it_an_anonymous_caller_still_cannot(self, client):
        body = _create_as_guest(client)

        response = _delete(client, body["short_code"])

        assert response.status_code == 401
        assert client.get(f"/{body['short_code']}").status_code == 302


class TestATokenIsWorthExactlyOneLink:

    def test_it_does_not_delete_a_different_link(self, client):
        mine = _create_as_guest(client)
        somebody_elses = _create_as_guest(client)

        response = _delete(
            client, somebody_elses["short_code"], token=mine["deletion_token"]
        )

        assert response.status_code == 401
        assert client.get(f"/{somebody_elses['short_code']}").status_code == 302

    @pytest.mark.parametrize(
        "token",
        ["", "not-a-token", "IjEyMyI.aaaaaaaaaaaaaaaaaaaaaaaaaaa"],
    )
    def test_a_forged_token_is_worth_nothing(self, client, token):
        body = _create_as_guest(client)

        response = _delete(client, body["short_code"], token=token)

        assert response.status_code == 401

    def test_a_tampered_token_is_worth_nothing(self, client):
        body = _create_as_guest(client)
        token = body["deletion_token"]
        # Flip a character in the payload, which is the part before the dot.
        payload, _, signature = token.partition(".")
        forged = f"{payload[:-1]}{'A' if payload[-1] != 'A' else 'B'}.{signature}"

        response = _delete(client, body["short_code"], token=forged)

        assert response.status_code == 401

    def test_the_token_dies_with_its_link(self, client):
        """
        It names the row, not the code. A code freed by deletion can be
        issued again, and a token naming the code would go on deleting
        whatever link took it next.
        """
        body = _create_as_guest(client)
        token = body["deletion_token"]
        assert _delete(client, body["short_code"], token=token).status_code == 200

        again = _delete(client, body["short_code"], token=token)

        assert again.status_code == 404


class TestATokenIsIssuedOnceToWhoeverCreatedTheLink:
    """
    Guests deduplicate by address. Two people behind one NAT asking for the
    same URL get the same link back -- and the second used to get the
    first's token with it, which is exactly the "the same address is a
    different person" case the token exists so as not to rely on.
    """

    @staticmethod
    def _behind_one_nat(client, url, address):
        """Shorten as one of several people sharing an outgoing address."""
        return client.post(
            "/api/v1/shorten",
            json={"url": url},
            headers=csrf_headers(client),
            environ_base={"REMOTE_ADDR": address},
        ).get_json()

    def test_a_deduplication_hit_carries_no_token(self, client):
        url, nat = _url(), "198.51.200.1"
        first = self._behind_one_nat(client, url, nat)

        second = self._behind_one_nat(client, url, nat)

        assert first["deletion_token"]
        assert second["is_new"] is False
        assert second["short_code"] == first["short_code"]
        assert second["deletion_token"] is None

    def test_the_second_caller_cannot_delete_the_first_ones_link(self, client):
        """The link is theirs to use, not theirs to remove."""
        url, nat = _url(), "198.51.200.2"
        self._behind_one_nat(client, url, nat)
        second = self._behind_one_nat(client, url, nat)

        response = _delete(client, second["short_code"])

        assert response.status_code == 401


class TestABatchGuestLinkCanBeTakenBackToo:
    """
    A guest who shortened ten URLs at once could not delete any of them,
    while a guest who shortened one could. Same claim, two endpoints.
    """

    def _batch(self, client, urls):
        return client.post(
            "/api/v1/batch/shorten",
            json={"urls": urls},
            headers=csrf_headers(client),
            environ_base={"REMOTE_ADDR": _address()},
        ).get_json()

    def test_every_new_item_carries_a_token(self, client):
        body = self._batch(client, [_url(), _url()])

        created = [item for item in body["results"] if item.get("is_new")]
        assert created
        assert all(item["deletion_token"] for item in created)

    def test_the_token_deletes_that_item(self, client):
        body = self._batch(client, [_url()])
        item = body["results"][0]

        response = _delete(client, item["short_code"], token=item["deletion_token"])

        assert response.status_code == 200, response.get_json()

    def test_an_account_batch_gets_no_tokens(self, client):
        token = register_and_login(
            client, email=f"batch-{uuid.uuid4().hex}@example.com"
        )
        body = client.post(
            "/api/v1/batch/shorten",
            json={"urls": [_url()]},
            headers=csrf_headers(client, auth_headers(token)),
        ).get_json()

        assert all(
            item.get("deletion_token") is None for item in body["results"]
        )
