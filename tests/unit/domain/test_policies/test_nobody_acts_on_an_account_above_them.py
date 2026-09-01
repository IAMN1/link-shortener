"""Reaching an account is as much an authority as granting a permission.

``require_may_confer`` guards the giving half: nobody hands out what they
do not hold. Nothing guarded the taking half, and deleting, deactivating
and re-roling all take rather than give -- so none of them passed through
it.

What that allowed, in the shipped role set's own terms: a role carrying
``admin:manage_users`` and nothing else could delete the only ``auditor``,
or strip its roles, and with it the only account able to read the audit
journal. ``admin:all`` deliberately does not carry ``audit:view``
(``BEYOND_ADMIN_ALL``), which is the whole point of that separation -- and
it was reachable around the back.

The shipped ``roles.yaml`` does not make such a role, so the path needed
one an operator wrote. That is a reason it was not urgent and not a reason
it was safe: the role editor exists precisely so operators write roles.
"""

import pytest

from link_shortener.domain.entities.permission import Permission
from link_shortener.domain.entities.role import Role
from link_shortener.domain.entities.user import User
from link_shortener.domain.exceptions import PermissionDeniedError
from link_shortener.domain.policies.privilege_policy import (
    is_privileged, require_may_act_on,
)
from link_shortener.domain.system_permissions import SystemPermissions
from link_shortener.domain.value_objects.email import Email
from link_shortener.domain.value_objects.password_hash import PasswordHash


def a_role(name: str, *permissions: str) -> Role:
    """
    Build a role granting exactly these permissions.

    Args:
        name: The role's name.
        *permissions: Permission names in ``resource:action`` form.

    Returns:
        The role.
    """
    return Role(
        id=f"role-{name}",
        name=name,
        permissions=tuple(
            Permission(
                id=f"perm-{permission}",
                name=permission,
                resource=permission.split(":")[0],
                action=permission.split(":")[1],
            )
            for permission in permissions
        ),
    )


def a_user(*roles: Role, email: str = "person@example.com") -> User:
    """
    Build an account wearing these roles.

    Args:
        *roles: The roles it holds.
        email: Its address, when a test needs two distinct accounts.

    Returns:
        The user entity.
    """
    user = User.create(
        email=Email(email),
        password_hash=PasswordHash("$2b$12$" + "x" * 53),
    )
    user.roles = list(roles)
    return user


MANAGER = a_role("user-manager", SystemPermissions.ADMIN_MANAGE_USERS.value)
AUDITOR = a_role("auditor", SystemPermissions.AUDIT_VIEW.value)
SUPERUSER = a_role("admin", SystemPermissions.ADMIN_ALL.value)


class TestWhichPermissionsCountAsAuthority:
    """Where the line is drawn, permission by permission.

    ``is_privileged`` is a rule rather than a list, so that a permission
    added later is classified rather than missed. That makes it worth
    writing down what the rule currently decides about every permission
    this service defines: adding one changes this table, and changing this
    table is how the decision gets noticed.

    The failure the tight half guards against is silent and one-sided -- a
    new administrative permission nobody classified would leave the
    accounts holding it reachable by anyone who may manage users.
    """

    @pytest.mark.parametrize(
        "permission",
        [
            "admin:all",
            "admin:manage_users",
            "admin:view_users",
            "admin:manage_roles",
            "admin:view_roles",
            "admin:view_system_health",
            "audit:view",
            "logs:view",
            "link:delete_any",
            "stats:view_any",
        ],
    )
    def test_authority(self, permission):
        assert is_privileged(permission)

    @pytest.mark.parametrize(
        "permission",
        [
            "link:create",
            "link:view_own",
            "link:delete_own",
            "stats:view_basic",
            "stats:view_full",
        ],
    )
    def test_use(self, permission):
        """What an account gets by signing up, plus one aggregate.

        ``stats:view_full`` is the service-wide popular-links breakdown.
        It is wider than an ordinary account's view and still not a reach
        into anybody's account, which is the line this rule draws.
        """
        assert not is_privileged(permission)

    def test_every_defined_permission_is_covered_by_the_table_above(self):
        """The two lists together are the whole enumeration.

        Without this, adding a permission and forgetting to classify it
        leaves both lists passing and the new name judged by a rule
        nobody looked at.
        """
        listed = {
            "admin:all", "admin:manage_users", "admin:view_users",
            "admin:manage_roles", "admin:view_roles",
            "admin:view_system_health", "audit:view", "logs:view",
            "link:delete_any", "stats:view_any", "link:create",
            "link:view_own", "link:delete_own", "stats:view_basic",
            "stats:view_full",
        }
        defined = {member.value for member in SystemPermissions}

        assert defined == listed, (
            "the permissions this service defines have changed; classify "
            "the new one in the table above"
        )


class TestAnAccountHoldingMoreIsOutOfReach:
    """The rule itself."""

    def test_a_manager_may_not_act_on_an_auditor(self):
        """The case the rule was written for."""
        with pytest.raises(PermissionDeniedError):
            require_may_act_on(a_user(MANAGER), a_user(AUDITOR, email="a@b.co"))

    def test_the_refusal_names_what_was_out_of_reach(self):
        """An administrator being refused should learn which grant did it.

        The same field ``require_may_confer`` fills, and for the same
        reason: the journal reads both as one kind of event.
        """
        with pytest.raises(PermissionDeniedError) as refused:
            require_may_act_on(a_user(MANAGER), a_user(AUDITOR, email="a@b.co"))

        # A tuple, not the list that was passed in: ``PermissionDeniedError``
        # freezes what it carries, so a handler cannot edit the record on
        # its way out.
        assert refused.value.exceeded == (SystemPermissions.AUDIT_VIEW.value,)

    def test_a_manager_may_act_on_an_ordinary_account(self):
        """The rule must not refuse the work the role exists to do.

        The account holds what signing up gives, and an administrative
        role carries none of it. Written as a plain set difference the
        rule refused exactly this -- which is how the narrowing came to be
        needed rather than assumed.
        """
        ordinary = a_role(
            "user", "link:create", "link:view_own", "link:delete_own",
            "stats:view_basic",
        )

        require_may_act_on(a_user(MANAGER), a_user(ordinary, email="a@b.co"))

    def test_a_manager_may_act_on_another_manager(self):
        """Equal authority is not excess authority."""
        require_may_act_on(
            a_user(MANAGER), a_user(MANAGER, email="a@b.co")
        )


class TestTheSuperuserIsNotBoundByIt:
    """``admin:all`` passes here, as it does in ``require_may_confer``."""

    def test_a_superuser_may_act_on_an_auditor(self):
        """Whatever the target holds, ``admin:all`` outranks it.

        That ``admin:all`` does not itself *carry* ``audit:view`` is a
        separate rule about reading the journal, not about who may
        administer an account.
        """
        require_may_act_on(
            a_user(SUPERUSER), a_user(AUDITOR, email="a@b.co")
        )


class TestSelfIsAlwaysAllowed:
    """An account is never above itself."""

    def test_an_auditor_may_act_on_their_own_account(self):
        """Otherwise the last auditor could not deactivate themselves.

        The difference between what the target holds and what the actor
        holds is empty when they are the same account, so this falls out
        of the rule rather than being an exception written into it.
        """
        auditor = a_user(AUDITOR)

        require_may_act_on(auditor, auditor)


class TestWhatTheRuleDoesNotAnswer:
    """The two ``None`` cases, and which of them is a refusal."""

    def test_an_absent_target_passes(self):
        """"No such user" is the use case's answer, not this rule's.

        Refusing here first would let a caller learn which ids exist from
        the shape of the refusal.
        """
        require_may_act_on(a_user(MANAGER), None)

    def test_an_anonymous_actor_holding_nothing_is_refused(self):
        """An actor with no permissions may reach no account that has any.

        Nothing reaches these use cases anonymously -- the routes require
        a permission first -- so this is the rule being total rather than
        a path in service.
        """
        with pytest.raises(PermissionDeniedError):
            require_may_act_on(None, a_user(AUDITOR, email="a@b.co"))

    def test_an_anonymous_actor_may_reach_an_account_holding_nothing(self):
        """The empty difference, from the other end."""
        require_may_act_on(None, a_user(email="a@b.co"))
