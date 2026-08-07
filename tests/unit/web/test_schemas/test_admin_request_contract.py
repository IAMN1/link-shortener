"""
Tests that the admin schema promises what the service actually enforces.

``CreateUserRequest`` declared ``min_length=6`` and described the field as
"min 6 symbols", while the domain policy refuses anything under eight. No
password could actually be set weaker -- the check lives in the hashing
every path goes through -- so nothing was exploitable. What was wrong is the
contract: an operator reading the schema, or a client generated from it,
would have believed six, and a disagreement between the stated rule and the
enforced one is the shape a hole arrives in later, when somebody trusts the
schema and removes the check.
"""

from link_shortener.domain.policies.password_policy import MIN_PASSWORD_LENGTH
from link_shortener.web.schemas.admin.admin_request import CreateUserRequest


class TestThePasswordFloorIsTheDomainsFloor:

    def test_the_schema_asks_for_what_the_policy_requires(self):
        schema = CreateUserRequest.model_json_schema()

        assert schema["properties"]["password"]["minLength"] == MIN_PASSWORD_LENGTH

    def test_the_description_does_not_promise_less(self):
        schema = CreateUserRequest.model_json_schema()
        description = schema["properties"]["password"]["description"]

        assert str(MIN_PASSWORD_LENGTH) in description

    def test_a_password_under_the_floor_is_refused_by_the_schema(self):
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CreateUserRequest(email="a@b.co", password="a" * (MIN_PASSWORD_LENGTH - 1))
