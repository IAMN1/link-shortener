"""
The status a caller actually meets when a body carries a field this
service never declared.

``StrictRequest`` refuses the field; the status the refusal arrives with
is decided elsewhere, by the ``VALIDATION_ERROR`` entry in
``error_handler.py``. Nothing held the two together, and they parted: the
docstring at ``strict.py`` said ``422`` while the running service answered
``400`` -- measured on a live stack, ``POST /api/v1/shorten`` with
``{"url": ..., "custom_code": "mycode1"}`` answering ``400
VALIDATION_ERROR`` with ``extra_forbidden`` on ``custom_code``. Decisions
lists ``422`` among the statuses this service does not answer with at all,
so ``400`` was right and the sentence was wrong.

The existing test for this rule, ``test_a_request_refuses_what_it_does_not
_declare.py``, holds the property over every request model -- but it asks
the models directly, through ``pytest.raises(ValidationError)``, and never
sends a request. A model that refuses correctly behind a handler that
answers with a different status would pass it. This file sends the
request.

The number is read out of the sentence rather than written here again: a
docstring claiming a status is a promise to a reader, and the only way it
stays true is for the promise itself to be what the test checks.
"""

import re

import pytest

from link_shortener.web.schemas import strict


PROMISED_STATUS = re.compile(
    r"refused when it carries a field this service does not\s+"
    r"declare, with `(\d{3})`"
)
"""The status ``strict.py`` promises, taken from its own docstring."""


def promised_status() -> int:
    """
    The status named in the sentence at the top of ``strict.py``.

    Returns:
        The three-digit status the docstring promises.

    Raises:
        AssertionError: If the sentence is no longer there to read. A
            rewritten docstring is not a licence to stop checking -- it is
            the moment to point this pattern at the new wording.
    """
    found = PROMISED_STATUS.search(strict.__doc__ or "")
    assert found, (
        "strict.py no longer states the status an undeclared field is "
        "refused with; the sentence this test reads has been rewritten"
    )
    return int(found.group(1))


class TestAnUndeclaredFieldInABody:

    def test_the_docstring_still_names_a_status(self):
        """The sentence is there and names a three-digit status."""
        assert 400 <= promised_status() <= 599

    def test_the_promise_is_not_one_the_service_never_makes(self):
        """
        The status promised is one this service actually answers with.

        ``422`` is on the list in Decisions of statuses that arrive only
        from Werkzeug or a proxy. Promising one of those is promising an
        answer no route of this service can give.
        """
        assert promised_status() != 422

    def test_the_service_answers_with_the_status_it_promises(self, client):
        """
        The refusal arrives with the status the docstring names.

        ``custom_code`` is the field that started this: it is the one a
        caller had reason to send, and the one the service silently
        ignored while answering ``201``.
        """
        response = client.post(
            "/api/v1/shorten",
            json={
                "url": "https://example.com/undeclared-field",
                "custom_code": "mycode1",
            },
        )

        assert response.status_code == promised_status()

    def test_the_refusal_names_the_field(self, client):
        """
        The body says which field was refused, and why.

        Without the name the caller learns only that something was wrong
        with a request they believe is correct.
        """
        response = client.post(
            "/api/v1/shorten",
            json={
                "url": "https://example.com/undeclared-field-named",
                "custom_code": "mycode1",
            },
        )

        body = response.get_json()
        assert body["error"] == "VALIDATION_ERROR"
        assert [d["field"] for d in body["details"]] == ["custom_code"]
        assert body["details"][0]["code"] == "extra_forbidden"

    @pytest.mark.parametrize("field", ["short_code", "ttl", "nonsense"])
    def test_any_undeclared_name_is_refused_the_same_way(self, client, field):
        """
        The rule is about undeclared fields, not about one field.

        ``custom_code`` alone would pass with a check written for that
        name; these are three names nothing in the request model declares.
        """
        response = client.post(
            "/api/v1/shorten",
            json={"url": "https://example.com/undeclared", field: "x"},
        )

        assert response.status_code == promised_status()
        assert response.get_json()["details"][0]["field"] == field
