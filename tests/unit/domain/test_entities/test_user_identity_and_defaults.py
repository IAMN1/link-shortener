"""
What an account is when nothing else has touched it yet.

``User`` was reached only through the use cases that build one, and each
of those passes every field. So the entity's own answers went unheld: the
state a fresh account starts in, what identity means for it, and what it
says when compared with something that is not an account at all.

The default that matters most is ``email_verified``. It is the one field
whose wrong default hands out working accounts nobody proved they own,
and flipping it left the whole suite green -- measured.
"""

import pytest

from link_shortener.domain.entities.permission import Permission
from link_shortener.domain.entities.role import Role
from link_shortener.domain.entities.user import User
from link_shortener.domain.value_objects.email import Email
from link_shortener.domain.value_objects.password_hash import PasswordHash


def _user(**overrides) -> User:
    """An account made the way registration makes one."""
    fields = {
        "email": Email("person@example.com"),
        "password_hash": PasswordHash("$2b$12$" + "a" * 53),
    }
    fields.update(overrides)
    return User.create(**fields)


class TestWhatAFreshAccountStartsAs:

    def test_a_new_account_has_not_proven_its_address(self):
        """Self-registration is the caller this default is for: the
        confirmation mail exists because nobody has proven anything yet."""
        assert _user().email_verified is False

    def test_an_account_built_field_by_field_is_unproven_too(self):
        """Not through ``create``, which passes the flag on: the field's
        own default. Anything that rebuilds a ``User`` without naming
        every field -- a fixture, a repair script, a later mapper -- gets
        this one, and a default of ``True`` there hands out an account
        nobody proved they own."""
        user = User(
            id="user-1",
            email=Email("person@example.com"),
            password_hash=PasswordHash("$2b$12$" + "a" * 53),
        )

        assert user.email_verified is False
        assert user.is_active is True

    def test_an_account_an_operator_vouches_for_starts_proven(self):
        assert _user(email_verified=True).email_verified is True

    def test_a_new_account_is_switched_on(self):
        """``is_active`` is an administrator's decision, and no
        administrator has made one yet."""
        assert _user().is_active is True

    def test_a_new_account_wears_no_roles_unless_given_some(self):
        assert _user().roles == []

    def test_a_new_account_has_never_signed_in(self):
        assert _user().last_login is None

    def test_confirming_the_address_is_what_changes_it(self):
        user = _user()

        user.confirm_email()

        assert user.email_verified is True

    def test_switching_an_account_off_and_on_again(self):
        user = _user()

        user.deactivate()
        assert user.is_active is False

        user.activate()
        assert user.is_active is True


class TestIdentityIsTheId:

    def test_two_accounts_with_one_id_are_the_same_account(self):
        first, second = _user(), _user()
        second.id = first.id

        assert first == second
        assert hash(first) == hash(second)

    def test_two_accounts_with_different_ids_are_not(self):
        assert _user() != _user()

    def test_one_id_is_one_entry_in_a_set(self):
        """The reason ``__hash__`` exists at all, and nothing asked for it:
        a set of accounts collapses the duplicates the id says are one."""
        first, second = _user(), _user()
        second.id = first.id

        assert len({first, second}) == 1


class TestComparedWithSomethingThatIsNotAnAccount:

    @pytest.mark.parametrize(
        "other", ["person@example.com", 42, None, object()],
        ids=["an address", "a number", "nothing", "a bare object"],
    )
    def test_it_is_not_equal_and_does_not_raise(self, other):
        user = _user()

        assert user != other
        assert (user == other) is False


class TestPermissionsComeFromTheRoles:

    def _role(self, name, permission):
        resource, action = permission.split(":")
        return Role(
            id=f"role-{name}", name=name,
            permissions=(
                Permission(
                    id=f"perm-{permission}", name=permission,
                    resource=resource, action=action,
                ),
            ),
        )

    def test_an_account_with_no_roles_has_no_permissions(self):
        assert _user().has_permission("link:create") is False

    def test_one_role_granting_it_is_enough(self):
        user = _user(roles=[self._role("user", "link:create")])

        assert user.has_permission("link:create") is True

    def test_a_permission_no_role_grants_is_refused(self):
        user = _user(roles=[self._role("user", "link:create")])

        assert user.has_permission("admin:all") is False

    def test_any_of_several_roles_will_do(self):
        user = _user(roles=[
            self._role("user", "link:create"),
            self._role("analyst", "stats:view"),
        ])

        assert user.has_permission("stats:view") is True
