"""What a role may be called, asked of the rule rather than of a schema.

The rule was a set of constants that only the admin API's Pydantic field
read. Roles arrive by a second route -- ``flask db load-custom-roles``,
which reads a YAML file -- and that route walked past it: a role named
``a/b`` was created, and ``DELETE /api/v1/admin/roles/a/b`` cannot address
it, because Werkzeug's default converter stops at the slash. Nothing short
of SQL could take it out again.
"""

import pytest

from link_shortener.domain import ValidationError
from link_shortener.domain.policies.role_policy import (
    ROLE_NAME_MAX_LENGTH, ROLE_NAME_MIN_LENGTH, require_valid_role_name,
)


class TestNamesTheRuleAccepts:
    """Everything the service itself ships, and what an operator would add."""

    @pytest.mark.parametrize("name", [
        "guest", "user", "analyst", "auditor", "admin",
        "content-editor", "content_editor", "tier2", "Ops",
    ])
    def test_a_usable_name_passes(self, name):
        require_valid_role_name(name)

    @pytest.mark.parametrize("length", [
        ROLE_NAME_MIN_LENGTH, ROLE_NAME_MAX_LENGTH,
    ])
    def test_both_ends_of_the_range_are_inside_it(self, length):
        """Inclusive bounds: the column is built from the same constant."""
        require_valid_role_name("r" * length)


class TestNamesTheRuleRefuses:
    """Each for its own reason, all of them named in the module docstring."""

    @pytest.mark.parametrize("name, why", [
        ("a/b", "a slash makes a name no route can address"),
        ("..", "reads as a traversal to whoever joins it onto a path"),
        ("two words", "a space is not in the allowed set"),
        ("line\nbreak", "travels into every log line written about it"),
        ("   ", "indistinguishable from another in any list"),
        ("", "an empty name is no name"),
        ("emoji-\U0001f600", "outside the allowed set"),
    ])
    def test_a_dangerous_name_is_refused(self, name, why):
        with pytest.raises(ValidationError) as refusal:
            require_valid_role_name(name)

        assert refusal.value.field == "name", why

    @pytest.mark.parametrize("length", [
        ROLE_NAME_MIN_LENGTH - 1, ROLE_NAME_MAX_LENGTH + 1,
    ])
    def test_a_name_outside_the_range_is_refused(self, length):
        """One over the column width is a 500 on PostgreSQL, not a 400."""
        with pytest.raises(ValidationError) as refusal:
            require_valid_role_name("r" * length)

        assert refusal.value.field == "name"
        assert str(ROLE_NAME_MAX_LENGTH) in refusal.value.message

    def test_something_that_is_not_a_string_is_refused(self, ):
        """A YAML file can put anything at all under ``name``."""
        with pytest.raises(ValidationError):
            require_valid_role_name(None)

