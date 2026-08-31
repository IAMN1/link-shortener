"""What a request body does with a field this service never declared.

Pydantic ignores it. For a response that is right; for a request it means
the service answers `201` to a call it did not carry out, which is the one
answer a caller cannot tell from success.

Measured on three separate live walks: `POST /api/v1/shorten` with
`{"url": ..., "custom_code": "mycode1"}` answered `201` with a generated
code every time, and asking again with the same `custom_code` produced
another generated one. There is no custom code in the HTTP API — it exists
only on `flask link create --code` — and the caller had no way to learn
they had not been given one.

Held as a property over the models as discovered, not as a list: a request
body added later is covered without anybody remembering this file, which
is the kind of remembering that failed for `minlength` and for the
password floor before it.
"""

import importlib
import inspect
import pkgutil

import pytest
from pydantic import BaseModel, ValidationError

import link_shortener.web.schemas as schemas
from link_shortener.web.schemas.strict import StrictRequest


LENIENT_ON_PURPOSE = {"RefreshTokenRequest"}
"""The one body that stays lenient, and the reason is at the class.

It is optional — a browser reaches `/auth/refresh` and `/auth/logout` with
no body, its token being in the cookie — and both routes build it from
whatever arrived. Strict, a stray field in a logout body refuses the
logout: a security action blocked over a field the route did not need.
"""


def request_models():
    """Every Pydantic model in `web.schemas` whose name ends in Request."""
    found = {}
    for module in pkgutil.walk_packages(schemas.__path__, f"{schemas.__name__}."):
        loaded = importlib.import_module(module.name)
        for name, value in vars(loaded).items():
            if (
                inspect.isclass(value)
                and issubclass(value, BaseModel)
                and name.endswith("Request")
                and value is not StrictRequest
            ):
                found[name] = value
    return found


class TestEveryRequestBodyIsStrict:

    def test_the_models_were_found(self):
        """
        A discovery that finds nothing passes every check below in
        silence.
        """
        found = request_models()

        assert len(found) >= 10, sorted(found)
        assert "CreateShortLinkRequest" in found, sorted(found)

    def test_the_exception_list_names_only_models_that_exist(self):
        """
        And a name that stopped existing would quietly excuse nothing --
        or, worse, excuse a model somebody renamed into it.
        """
        unknown = LENIENT_ON_PURPOSE - set(request_models())

        assert not unknown, f"the exception list names {sorted(unknown)}"

    @pytest.mark.parametrize(
        "name", sorted(set(request_models()) - LENIENT_ON_PURPOSE)
    )
    def test_it_refuses_a_field_it_does_not_declare(self, name):
        # Taken out of the parametrisation rather than skipped inside it:
        # this suite is run with `--error-for-skips`, and a skip is how a
        # check stops being one without saying so.
        model = request_models()[name]

        assert model.model_config.get("extra") == "forbid", (
            f"{name} ignores a field it does not declare, so a caller who "
            f"asks for something this service does not do is answered as "
            f"though it did"
        )

    def test_the_field_that_started_this_is_refused_by_name(self):
        """
        The measured case, end to end through the model rather than
        through its configuration.
        """
        from link_shortener.web.schemas.requests import CreateShortLinkRequest

        with pytest.raises(ValidationError) as refused:
            CreateShortLinkRequest(
                url="https://example.com/x", custom_code="mycode1"
            )

        assert "custom_code" in str(refused.value)

    def test_a_body_this_service_does_declare_still_works(self):
        """
        The other half: strictness must not refuse what the forms send.
        """
        from link_shortener.web.schemas.requests import CreateShortLinkRequest

        built = CreateShortLinkRequest(
            url="https://example.com/x", ttl_seconds=3600
        )

        assert built.ttl_seconds == 3600

    def test_the_lenient_one_is_still_lenient(self):
        """
        And the exception stays an exception: a stray field in a logout
        body must not refuse the logout.
        """
        from link_shortener.web.schemas.auth_requests import (
            RefreshTokenRequest
        )

        built = RefreshTokenRequest(refresh_token=None, stray="ignored")

        assert built.refresh_token is None
