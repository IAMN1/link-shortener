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

from link_shortener.domain.exceptions import ValidationError as DomainError
from link_shortener.domain.policies.password_policy import MIN_PASSWORD_LENGTH
from link_shortener.domain.policies.role_policy import (
    ROLE_DESCRIPTION_MAX_LENGTH, ROLE_NAME_MAX_LENGTH, ROLE_NAME_PATTERN,
)
from link_shortener.domain.value_objects.email import Email
from link_shortener.web.schemas.admin.admin_request import (
    CreateRoleRequest, CreateUserRequest, UpdateRolePermissionsRequest,
    UpdateUserRolesRequest,
)


GOOD_PASSWORD = "a-password-of-their-own"
"""Past the domain's floor, so nothing below fails on the wrong field."""


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
        # Against the migration, which is a literal, and not against the ORM
        # model: the model builds its column from ``ROLE_NAME_MAX_LENGTH``
        # and the schema takes its bound from the same constant, so the two
        # moved together. Measured on that comparison: widening the constant
        # to 80 left this line green while the deployed column stayed at 50.
        assert published["maxLength"] == column_width_in_migration(
            "roles", "name"
        )


MIGRATION = (
    Path(__file__).resolve().parents[4]
    / "migrations" / "versions" / "0001_initial_schema.py"
)
"""The baseline migration, which is what a migrated database is built from."""


def column_width_in_migration(table, column):
    """
    Read one column's declared width out of the baseline migration.

    Args:
        table: Table name as written in ``op.create_table``.
        column: Column name to look up inside that table's block.

    Returns:
        The declared ``String(length=...)`` as an int.
    """
    text = MIGRATION.read_text()
    block = text[text.index(f"op.create_table('{table}'"):]
    block = block[:block.index("\n    )")]
    found = re.search(
        rf"sa\.Column\('{column}', sa\.String\(length=(\d+)\)", block
    )
    assert found, f"no {table}.{column} in {MIGRATION.name}"
    return int(found.group(1))


class TestTheWidthsAgreeWithTheMigratedDatabase:
    """The width PostgreSQL enforces is a literal in the migration.

    The ORM model builds the schema only for ``create_all`` on SQLite,
    where a ``VARCHAR`` length is not checked at all, so a constant widened
    on its own leaves the deployed column exactly where it was and puts the
    500 back. Measured: ``ROLE_NAME_MAX_LENGTH = 80`` keeps every other
    test in this file green while ``0001_initial_schema.py`` still says 50.
    """

    def test_the_name_bound_is_the_width_the_migration_creates(self):
        assert column_width_in_migration("roles", "name") == ROLE_NAME_MAX_LENGTH

    def test_the_description_bound_is_the_width_the_migration_creates(self):
        assert (
            column_width_in_migration("roles", "description")
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


class TestTheAddressHasToBeOne:
    """The email rule had no negative case at all.

    Measured on the mutation run of 2026-08-10: removing the pattern from
    the field survived the whole suite, and so did removing its anchors --
    which in pydantic's Rust engine turns the rule into a search, so
    ``"a b@c.d junk@"`` passes on the part of it that matches.
    """

    @pytest.mark.parametrize("address", [
        "newuser@example.com",
        "a@b.c",
        "first.last+tag@sub.example.co.uk",
    ])
    def test_an_ordinary_address_is_accepted(self, address):
        """The premise: a rule that refuses everything passes every test
        below and stops any account from being created at all.

        Args:
            address: An address the service must go on taking.
        """
        assert CreateUserRequest(
            email=address, password=GOOD_PASSWORD
        ).email == address

    @pytest.mark.parametrize("address", [
        "notanemail",           # no @ at all
        "@example.com",         # nothing to the left of it
        "user@",                # nothing to the right
        "user@example",         # no dot in the domain
        "user@@example.com",    # two, so neither side is a part
        # Two addresses in one field, which is what a rule guarding only
        # the left of the last `@` lets through -- measured: with the third
        # class widened to `[^\s]` both validators took it, and the value
        # would have decided who a message goes to.
        "user@example.com@evil.example",
        "victim@bank.example@attacker.test",
        "a b@c.d junk@",        # the one an unanchored rule lets through
        "",
    ])
    def test_something_that_is_not_an_address_is_refused(self, address):
        """
        Args:
            address: A value the schema must not accept.
        """
        with pytest.raises(ValidationError):
            CreateUserRequest(email=address, password=GOOD_PASSWORD)

    @pytest.mark.parametrize("address", [
        "user@example.com\n",   # `$` in Python matches before this one
        "user@ex\nample.com",   # `[^@]` used to admit it outright
        "a b@c.d",              # a space is not part of an unquoted address
        "user@exa mple.com",
        "\tuser@example.com",
        "user@exa\x1cmple.com",  # the four the two engines disagreed about
        "user@exa\x1fmple.com",
        # Not only the three obvious ones: a rule spelled out as
        # `[^@ \t\n]` passes every one of these, and a lone CR ends the
        # line for most readers of a log file.
        "user@example.com\r",
        "user@ex\rample.com",
        "user@example.com\x0b",
        "user@example.com\x0c",
        "user@exa\xa0mple.com",
    ])
    def test_whitespace_does_not_travel_inside_an_address(self, address):
        """The address is written into every log line and audit record
        about the account, and into a mail header once that channel
        exists, where a newline is how a header injection is spelled.

        Args:
            address: A value carrying whitespace the schema must refuse.
        """
        with pytest.raises(ValidationError):
            CreateUserRequest(email=address, password=GOOD_PASSWORD)


class TestTheSchemaAndTheDomainAgreeOnAnAddress:
    """Two validators, one rule, and two regex engines under them.

    The schema is checked by the Rust ``regex`` crate through pydantic and
    the value object by Python's ``re``, and the two agree on neither the
    anchor nor the shorthand class: Python's ``$`` also matches just before
    a trailing newline, and Python's ``\\s`` counts the four information
    separators U+001C..U+001F where the Rust crate does not. So the rule is
    written twice, once per engine, and this is what keeps the two
    spellings answering the same -- asked of addresses rather than of the
    expressions, which would only compare a constant against itself.

    The four separators are in the list below because they were the whole
    of a real disagreement: with ``\\s`` alone and nothing spelled out, the
    schema took ``"user@exa\\x1cmple.com"`` and the value object then
    refused it -- measured on the live endpoint as a 400 raised a layer
    deeper than the one that names the field.
    """

    @pytest.mark.parametrize("address", [
        "newuser@example.com",
        "a@b.c",
        "notanemail",
        "@example.com",
        "user@",
        "user@example",
        "user@@example.com",
        "a b@c.d junk@",
        "user@example.com\n",
        "user@ex\nample.com",
        "a b@c.d",
        "user@exa\x1cmple.com",
        "user@exa\x1dmple.com",
        "user@exa\x1emple.com",
        "user@exa\x1fmple.com",
        "",
    ])
    def test_both_give_the_same_verdict(self, address):
        """
        Args:
            address: The value put to both validators.
        """
        try:
            CreateUserRequest(email=address, password=GOOD_PASSWORD)
            schema_took_it = True
        except ValidationError:
            schema_took_it = False

        try:
            Email(address)
            domain_took_it = True
        except DomainError:
            domain_took_it = False

        assert schema_took_it == domain_took_it, (
            f"{address!r}: the schema says {schema_took_it} and the value "
            f"object says {domain_took_it}"
        )


class TestAnAccountArrivesUsable:
    """``is_active`` defaults to ``True``, and the default is the contract.

    Measured: flipping it to ``False`` survived the whole suite. An
    administrator creating an account without naming the field would get
    one that cannot sign in, and nothing in the answer says why.
    """

    def test_an_account_created_without_the_field_is_active(self):
        assert CreateUserRequest(
            email="newuser@example.com", password=GOOD_PASSWORD
        ).is_active is True

    def test_the_published_schema_says_so_too(self):
        """What a generated client reads before it sends anything."""
        published = CreateUserRequest.model_json_schema()

        assert published["properties"]["is_active"]["default"] is True

    def test_an_inactive_account_can_still_be_asked_for(self):
        assert CreateUserRequest(
            email="newuser@example.com",
            password=GOOD_PASSWORD,
            is_active=False,
        ).is_active is False


class TestAnEmptyListIsNotAnUpdate:
    """``min_length=1`` on three fields, and nothing held any of them.

    Measured: removing it from each survived the whole suite. An empty
    ``roles`` takes every role off a user and an empty ``permissions``
    empties a role -- through an endpoint whose name says it is replacing
    them, so the answer is a 200 and the account quietly has nothing.
    """

    def test_a_user_cannot_be_left_with_no_roles(self):
        with pytest.raises(ValidationError):
            UpdateUserRolesRequest(roles=[])

    def test_a_role_cannot_be_created_with_no_permissions(self):
        with pytest.raises(ValidationError):
            CreateRoleRequest(name="editor", permissions=[])

    def test_a_role_cannot_be_emptied_of_permissions(self):
        with pytest.raises(ValidationError):
            UpdateRolePermissionsRequest(permissions=[])

    def test_one_entry_is_enough(self):
        # The premise: a rule that refuses every list would pass all three
        # above and stop any role from being granted at all.
        assert UpdateUserRolesRequest(roles=["user"]).roles == ["user"]
        assert UpdateRolePermissionsRequest(
            permissions=["link:create"]
        ).permissions == ["link:create"]
