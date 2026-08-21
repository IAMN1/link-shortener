"""A role is the row it is, not the name it wears.

``Role`` and ``Permission`` both replace the equality a frozen dataclass
would generate with one that compares identifiers, and neither had a test:
the entities sat at 78% and 73%, with the comparison and the hash
unmeasured. What they decide is not academic -- a role deleted and created
again under its old name is a different role, and code that matched on the
name bound accounts to whichever row happened to hold it.
"""

from link_shortener.domain import Permission, Role
from link_shortener.domain.exceptions import RoleIsSystemError

import pytest


PERMISSION = Permission("p-1", "link:create", "link", "create")


class TestRoleIdentity:
    """Equality and hashing follow the id, and nothing else."""

    def test_the_same_id_under_a_different_name_is_the_same_role(self):
        renamed = Role(id="r-1", name="renamed")

        assert Role(id="r-1", name="editor") == renamed

    def test_the_same_name_under_a_different_id_is_not(self):
        """The case that matters: deleted, then made again."""
        assert Role(id="r-1", name="editor") != Role(id="r-2", name="editor")

    def test_it_is_not_equal_to_something_that_is_not_a_role(self):
        assert Role(id="r-1", name="editor") != "editor"
        assert Role(id="r-1", name="editor") != PERMISSION

    def test_a_set_of_roles_folds_by_id(self):
        held = {
            Role(id="r-1", name="editor"),
            Role(id="r-1", name="editor", description="read again"),
            Role(id="r-2", name="editor"),
        }

        assert len(held) == 2


class TestPermissionIdentity:
    """The same rule, one level down."""

    def test_the_same_id_is_the_same_permission(self):
        assert PERMISSION == Permission(
            "p-1", "link:create", "link", "create", "reworded"
        )

    def test_a_different_id_is_a_different_permission(self):
        assert PERMISSION != Permission("p-2", "link:create", "link", "create")

    def test_it_is_not_equal_to_something_that_is_not_a_permission(self):
        assert PERMISSION != "link:create"

    def test_a_set_of_permissions_folds_by_id(self):
        assert len({PERMISSION, Permission(
            "p-1", "link:create", "link", "create"
        )}) == 1


class TestWhatARoleRefuses:
    """The invariant the flag carries, asked of the entity that holds it."""

    def test_a_system_role_refuses_to_be_changed(self):
        with pytest.raises(RoleIsSystemError) as refusal:
            Role(id="r-1", name="guest", is_system=True).ensure_may_be_changed()

        assert refusal.value.role_name == "guest"

    def test_an_ordinary_role_does_not(self):
        Role(id="r-2", name="editor").ensure_may_be_changed()

    def test_a_role_grants_what_its_permissions_name(self):
        role = Role(id="r-3", name="editor", permissions=(PERMISSION,))

        assert role.has_permission("link:create")
        assert not role.has_permission("admin:all")
