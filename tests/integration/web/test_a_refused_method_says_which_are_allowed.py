"""
``405`` carries ``Allow``, and a credential does not change that answer.

RFC 9110 15.5.6 is not soft about the header: "The origin server MUST
generate an Allow header field in a 405 response containing a list of the
target resource's currently supported methods." It is also the only thing
that makes the refusal actionable -- a client told "not allowed" and
nothing else has to guess which verb to try.

Werkzeug puts the list on the exception it raises. This service replaced
that response with a JSON envelope of its own and left the header behind,
so every route answered 405 with no ``Allow`` at all. Found by the contract
run, which sends a request per method and reads the answer against the
standard rather than against anybody's expectation.

The second class below is the other half of the same answer. Refusing a
presented credential is right where the credential is what the endpoint
runs on -- but with no route matched there is no endpoint, and the answer
is about the request line: 404 for an address this service does not serve,
405 for a method this address does not take. Refusing first replaced both
with 401 and told the caller nothing they could act on.
"""

import pytest


PATHS_AND_A_METHOD_THEY_REFUSE = [
    ("/api/v1/stats", "DELETE"),
    ("/api/v1/links/mine", "POST"),
    ("/health", "PUT"),
    ("/api/v1/auth/login", "GET"),
]


class TestTheRefusalNamesWhatIsAllowed:

    @pytest.mark.parametrize("path, method", PATHS_AND_A_METHOD_THEY_REFUSE)
    def test_it_carries_the_header(self, client, path, method):
        answered = client.open(path, method=method)

        assert answered.status_code == 405
        assert answered.headers.get("Allow"), (
            f"{method} {path} refused without saying what is allowed"
        )

    def test_the_header_names_the_methods_that_do_work(self, client):
        """A list, not a placeholder: the caller acts on what is in it."""
        answered = client.open("/api/v1/stats", method="DELETE")

        allowed = {
            method.strip()
            for method in answered.headers["Allow"].split(",")
        }

        assert "GET" in allowed
        assert "DELETE" not in allowed

    def test_the_body_is_still_the_envelope_the_service_speaks(self, client):
        """
        The header is added to the answer, not put in place of it.

        A client reading `error` gets what it always got.
        """
        answered = client.open("/api/v1/stats", method="DELETE")

        assert answered.get_json()["error"] == "METHOD_NOT_ALLOWED"


class TestACredentialDoesNotReplaceThatAnswer:
    """
    With no rule matched there is no endpoint, and 401 would be an answer
    to a question the caller did not ask.
    """

    def test_a_refused_method_answers_405_even_with_a_bad_token(self, client):
        answered = client.open(
            "/api/v1/stats",
            method="DELETE",
            headers={"Authorization": "Bearer not.a.valid.token"},
        )

        assert answered.status_code == 405
        assert answered.headers.get("Allow")

    def test_an_address_that_does_not_exist_answers_404_with_one(self, client):
        answered = client.get(
            "/api/v1/nothing-here",
            headers={"Authorization": "Bearer not.a.valid.token"},
        )

        assert answered.status_code == 404

    def test_a_presented_token_is_still_refused_where_there_is_a_route(
        self, client
    ):
        """
        The half that keeps the exception narrow: on a route that exists,
        a credential the service cannot honour is still refused.
        """
        answered = client.get(
            "/api/v1/links/mine",
            headers={"Authorization": "Bearer not.a.valid.token"},
        )

        assert answered.status_code == 401
