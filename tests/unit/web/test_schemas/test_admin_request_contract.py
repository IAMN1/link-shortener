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

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from link_shortener.domain.policies.password_policy import MIN_PASSWORD_LENGTH
from link_shortener.domain.policies.role_policy import (
    ROLE_DESCRIPTION_MAX_LENGTH, ROLE_NAME_MAX_LENGTH, ROLE_NAME_PATTERN,
)
from link_shortener.infrastructure.database.models.role_model import RoleModel
from link_shortener.web.schemas.admin.admin_request import (
    CreateRoleRequest, CreateUserRequest,
)


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


class TestARoleNameIsBoundedByCharacters:
    """``name`` was bounded by ``min_length=2`` and nothing else.

    Measured against the live routes with the pattern removed: every name
    below creates with 201, and the two carrying a slash then answer 404 on
    ``GET`` and on ``DELETE`` -- the name is the last segment of the URL
    those routes are reached through, and Werkzeug's default converter
    "accepts any string but only one path segment". The role stayed in the
    database, addressable by nothing and removable by nothing short of SQL.

    The rest of the set is reachable and is refused on other grounds, which
    the two parametrize lists keep apart rather than blur.
    """

    @pytest.mark.parametrize("name", ["guest", "user", "analyst", "admin"])
    def test_the_names_this_application_ships_are_still_accepted(self, name):
        """Read off ``roles.yaml``: a pattern that refused one of these
        would refuse the roles the seed itself creates."""
        assert CreateRoleRequest(name=name, permissions=["link:create"]).name == name

    @pytest.mark.parametrize("name", ["role/with/slash", "../admin"])
    def test_a_name_no_route_can_address_is_refused(self, name):
        """Measured: 201 on create, 404 on GET and on DELETE."""
        with pytest.raises(ValidationError):
            CreateRoleRequest(name=name, permissions=["link:create"])

    @pytest.mark.parametrize("name", [
        "bad\nname",            # travels into every log line about the role
        "role with space",      # one spelling in a URL, another in a list
        "  ",                   # indistinguishable from any other such name
        "..",                   # reads as a traversal to whoever joins a path
        "%2e%2e",               # the same, already encoded
    ])
    def test_a_name_that_is_addressable_but_unwanted_is_refused_too(self, name):
        """These five do delete with 200 once created -- measured. They are
        out because of what they do elsewhere, not because of the route."""
        with pytest.raises(ValidationError):
            CreateRoleRequest(name=name, permissions=["link:create"])

    def test_a_name_wider_than_the_column_is_refused_by_the_schema(self):
        """On PostgreSQL the database refuses it, and a request meets that
        as a 500 instead of the 400 that says which field was wrong."""
        with pytest.raises(ValidationError):
            CreateRoleRequest(
                name="a" * (ROLE_NAME_MAX_LENGTH + 1),
                permissions=["link:create"],
            )

    def test_the_published_rule_refuses_a_slash(self):
        """Read against the pattern's behaviour, not against the constant
        it was built from: comparing the two moves both sides together, and
        replacing ``ROLE_NAME_PATTERN`` with ``.*`` would leave such a
        comparison green while reopening the hole this file exists to shut.
        """
        published = CreateRoleRequest.model_json_schema()["properties"]["name"]

        assert re.match(published["pattern"], "role/with/slash") is None
        assert re.match(published["pattern"], "ok_role") is not None
        assert published["maxLength"] == RoleModel.__table__.columns["name"].type.length


class TestTheWidthsAgreeWithTheMigratedDatabase:
    """The width PostgreSQL enforces is a literal in the migration.

    The ORM model builds the schema only for ``create_all`` on SQLite,
    where a ``VARCHAR`` length is not checked at all, so a constant widened
    on its own leaves the deployed column exactly where it was and puts the
    500 back. Measured: ``ROLE_NAME_MAX_LENGTH = 80`` keeps every other
    test in this file green while ``0001_initial_schema.py`` still says 50.
    """

    MIGRATION = (
        Path(__file__).resolve().parents[4]
        / "migrations" / "versions" / "0001_initial_schema.py"
    )

    def _column_width(self, table, column):
        """
        Read one column's declared width out of the baseline migration.

        Args:
            table: Table name as written in ``op.create_table``.
            column: Column name to look up inside that table's block.

        Returns:
            The declared ``String(length=...)`` as an int.
        """
        text = self.MIGRATION.read_text()
        block = text[text.index(f"op.create_table('{table}'"):]
        block = block[:block.index("\n    )")]
        found = re.search(
            rf"sa\.Column\('{column}', sa\.String\(length=(\d+)\)", block
        )
        assert found, f"no {table}.{column} in {self.MIGRATION.name}"
        return int(found.group(1))

    def test_the_name_bound_is_the_width_the_migration_creates(self):
        assert self._column_width("roles", "name") == ROLE_NAME_MAX_LENGTH

    def test_the_description_bound_is_the_width_the_migration_creates(self):
        assert (
            self._column_width("roles", "description")
            == ROLE_DESCRIPTION_MAX_LENGTH
        )


class TestADescriptionFitsTheColumnItIsStoredIn:
    """The same disagreement as the name had, on the field beside it.

    Measured on PostgreSQL 15 against ``VARCHAR(255)``: 256 characters
    raise ``StringDataRightTruncation``, which the caller meets as a 500
    rather than as a 400 naming the field. SQLite does not check the width,
    so nothing in the suite would have said so.
    """

    def test_a_description_past_the_column_is_refused_by_the_schema(self):
        with pytest.raises(ValidationError):
            CreateRoleRequest(
                name="editor",
                description="d" * (ROLE_DESCRIPTION_MAX_LENGTH + 1),
                permissions=["link:create"],
            )

    def test_one_that_fits_is_still_accepted(self):
        role = CreateRoleRequest(
            name="editor",
            description="d" * ROLE_DESCRIPTION_MAX_LENGTH,
            permissions=["link:create"],
        )

        assert len(role.description) == ROLE_DESCRIPTION_MAX_LENGTH
