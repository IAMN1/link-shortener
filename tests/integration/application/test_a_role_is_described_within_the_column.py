"""
Tests that the width of a role's description is enforced by the service.

The rule is stated three times on purpose: as a constant, as the admin
API's Pydantic field, and as ``require_valid_role_description``, which the
service and the YAML loader both call. The schema is the door HTTP callers
come through; it is not the only door. ``AdminService.create_role`` is
reached directly by anything that is not a request -- the CLI tests in
this suite call it that way -- and behind the schema the check has to
stand on its own.

Measured before the rule existed, through the other doorless door
(``flask db load-custom-roles``): 256 characters reached PostgreSQL and
came back ``StringDataRightTruncation``, a traceback out of the driver.
The same would arrive here.

This file exists because the service call was, for a while, held by
nothing: an audit of the suite removed it and every one of the 3864 tests
stayed green -- the only check anywhere near it was the contract test for
the Pydantic field, which holds the schema and says nothing about the
service behind it.
"""

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.domain import ValidationError
from link_shortener.domain.policies.role_policy import (
    ROLE_DESCRIPTION_MAX_LENGTH,
)


@pytest.fixture()
def admin_service(app):
    """The facade, and a context to call it with."""
    with app.app_context():
        yield (
            app.container.get_admin_service(),
            RequestContext(request_id="description-width-test"),
        )


class TestTheServiceRefusesWhatTheColumnCannotHold:

    def test_a_description_past_the_column_is_refused(self, admin_service):
        admin, context = admin_service

        with pytest.raises(ValidationError) as refusal:
            admin.create_role(
                "too-wordy",
                "d" * (ROLE_DESCRIPTION_MAX_LENGTH + 1),
                [],
                context,
            )

        assert refusal.value.field == "description"

    def test_the_role_is_not_created_by_the_refused_call(self, admin_service):
        """A refusal that still wrote the row would be no refusal."""
        admin, context = admin_service

        with pytest.raises(ValidationError):
            admin.create_role(
                "not-created",
                "d" * (ROLE_DESCRIPTION_MAX_LENGTH + 1),
                [],
                context,
            )

        assert admin.get_role("not-created", context) is None

    def test_a_description_the_column_holds_is_created(self, admin_service):
        """The bound is inclusive, and the neighbouring value goes in."""
        admin, context = admin_service

        role = admin.create_role(
            "wide-enough", "d" * ROLE_DESCRIPTION_MAX_LENGTH, [], context
        )

        assert len(role.description) == ROLE_DESCRIPTION_MAX_LENGTH
