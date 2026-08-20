"""What an administrator's actions leave in the audit journal.

The rule these tests hold is the one the vocabulary is built on: an act
that changes who may do what leaves a record. Every use case here passed
its whole existing suite writing nothing to the audit trail at all -- the
application logger took the line, and ``application.log`` is read under
``logs:view``, which is not the permission an investigation is granted.

The role events are the ones worth reading twice. Changing what a role
grants moves what every holder of it may do, at once, with no account
touched; an investigator asking why an account could suddenly do something
finds nothing against that account, and the answer is only here.
"""

from contextlib import contextmanager
from unittest.mock import Mock

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.current_user_info import CurrentUserInfo
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.use_cases.admin.roles.create_role import (
    CreateRoleUseCase,
)
from link_shortener.application.use_cases.admin.roles.delete_role import (
    DeleteRoleUseCase,
)
from link_shortener.application.use_cases.admin.roles.update_role_permissions import (
    UpdateRolePermissionsUseCase,
)
from link_shortener.application.use_cases.admin.users.activate_user import (
    ActivateUserUseCase,
)
from link_shortener.application.use_cases.admin.users.confirm_user_email import (
    ConfirmUserEmailUseCase,
)
from link_shortener.application.use_cases.admin.users.create_user import (
    CreateUserUseCase,
)
from link_shortener.application.use_cases.admin.users.deactivate_user import (
    DeactivateUserUseCase,
)
from link_shortener.application.use_cases.admin.users.update_user_role import (
    UpdateUserRolesUseCase,
)
from link_shortener.domain import SystemPermissions
from link_shortener.domain.entities.permission import Permission
from link_shortener.domain.entities.role import Role
from link_shortener.domain.entities.user import User
from link_shortener.domain import Email, PasswordHash


TARGET = "the-account-being-administered"
ADMINISTRATOR = "the-account-doing-the-administering"


def named(name):
    """
    A stand-in carrying a ``name``, which is all these records write.

    Args:
        name: What the role or permission is called.

    Returns:
        The stand-in.
    """
    thing = Mock()
    thing.name = name
    return thing


def user_with(*role_names):
    """
    An account holding the named roles.

    Args:
        role_names: Names of the roles it wears.

    Returns:
        The stand-in account.
    """
    account = Mock()
    account.id = TARGET
    account.roles = [named(name) for name in role_names]
    # Answered rather than left to the mock: a ``Mock`` is truthy, so the
    # guard would read every target as an administrator and go on to count
    # the ones remaining -- a comparison against another mock. The target
    # here is an ordinary account, which is what makes these tests about
    # the audit record rather than about the last-administrator rule.
    account.has_permission.return_value = False
    return account


def role_granting(name, *permission_names):
    """
    A role granting exactly the named permissions.

    Args:
        name: Name of the role.
        permission_names: Names of the permissions it grants.

    Returns:
        The stand-in role.
    """
    role = named(name)
    role.permissions = [named(p) for p in permission_names]
    return role


@pytest.fixture
def audit():
    """The audit logger, watched for what each action writes to it.

    ``bind`` answers with the same object: every use case binds the request
    context before writing, and a mock whose ``bind`` returned a fresh
    child would leave the assertions looking at an untouched original.
    """
    logger = Mock(spec=AuditLogger)
    logger.bind.return_value = logger
    return logger


def an_administrator() -> User:
    """
    The account making these requests, holding ``admin:all``.

    Real rather than a stand-in: the use cases run the privilege guard
    against whoever the context names, and a mock that satisfied it would
    also satisfy a guard that had been deleted.

    Returns:
        The administrator entity.
    """
    admin_all = SystemPermissions.ADMIN_ALL.value
    resource, action = admin_all.split(":", 1)
    role = Role(
        id="r-admin",
        name="admin",
        permissions=(
            Permission(
                id="p-admin-all",
                name=admin_all,
                resource=resource,
                action=action,
            ),
        ),
    )
    admin = User.create(
        email=Email("root@example.com"),
        password_hash=PasswordHash("not-checked-here"),
        roles=[role],
    )
    admin.id = ADMINISTRATOR
    return admin


@pytest.fixture
def stored():
    """What the database holds, by account id.

    A dictionary rather than one return value because two different reads
    go through ``find_by_id`` in the same transaction: the guard loading
    the administrator, and ``update_user_role`` loading the account whose
    roles are about to be replaced. A mock answering the same user to both
    would let a use case read the administrator's roles and write them
    down as the target's -- and pass.
    """
    return {ADMINISTRATOR: an_administrator()}


@pytest.fixture
def uow(stored):
    """A unit of work that answers whatever a test sets on it."""
    unit = Mock()
    unit.users.find_by_id.side_effect = stored.get
    unit.roles.get_by_name.return_value = None
    unit.refresh_sessions.revoke_all_for_user.return_value = 0
    return unit


@pytest.fixture
def uow_factory(uow):
    """A factory handing out that one unit of work."""

    @contextmanager
    def factory(*args, **kwargs):
        yield uow

    return factory


@pytest.fixture
def context():
    """A request made by the administrator the database holds."""
    return RequestContext(
        request_id="req-1",
        remote_addr="10.0.0.1",
        current_user=CurrentUserInfo(
            id=ADMINISTRATOR,
            email="root@example.com",
            roles=["admin"],
            is_active=True,
        ),
    )


class TestAccountsAreRecorded:
    """Creating, deleting, switching an account off and on again."""

    def test_a_created_account_is_recorded_with_what_it_was_given(
        self, uow_factory, audit, context
    ):
        service = Mock()
        service.create_user.return_value = user_with("user")
        use_case = CreateUserUseCase(
            uow_factory=uow_factory,
            user_service=service,
            logger=Mock(),
            audit_logger=audit,
        )

        use_case.execute("new@example.com", "pw", context)

        _, kwargs = audit.log_user_created.call_args
        assert kwargs["target_user_id"] == TARGET
        assert kwargs["email"] == "new@example.com"
        assert kwargs["roles"] == ["user"]

    def test_the_roles_come_off_the_account_not_off_the_request(
        self, uow_factory, audit, context
    ):
        """Asked for none, an account is given the default one.

        A record repeating the empty request would say an account was
        created with no entitlements at all -- which is the opposite of
        what happened, and the difference matters exactly when somebody is
        checking whether an account was created with more than it should
        have been.
        """
        service = Mock()
        service.create_user.return_value = user_with("user")
        use_case = CreateUserUseCase(
            uow_factory=uow_factory,
            user_service=service,
            logger=Mock(),
            audit_logger=audit,
        )

        use_case.execute("new@example.com", "pw", context, role_names=None)

        assert audit.log_user_created.call_args[1]["roles"] == ["user"]

    def test_a_deleted_account_is_recorded_with_what_went_with_it(
        self, uow, uow_factory, audit, context
    ):
        """The links go with the account and it is not reversible, so the
        count is the only remaining measure of what was destroyed."""
        from link_shortener.application.use_cases.admin.users.delete_user import (
            DeleteUserUseCase,
        )

        uow.links.delete_by_owner.return_value = []
        service = Mock()
        service.delete_user.return_value = True
        use_case = DeleteUserUseCase(
            uow_factory=uow_factory,
            user_service=service,
            cache=Mock(),
            redirect_cache=Mock(),
            stats_cache=Mock(),
            logger=Mock(),
            audit_logger=audit,
        )

        use_case.execute(TARGET, context)

        _, kwargs = audit.log_user_deleted.call_args
        assert kwargs["target_user_id"] == TARGET
        assert kwargs["links_deleted"] == 0

    def test_an_account_that_owned_nothing_still_leaves_a_record(
        self, uow, uow_factory, audit, context
    ):
        """The link records are the trail of what was destroyed; this is
        the trail of the account, and an account with no links writes no
        link records at all."""
        from link_shortener.application.use_cases.admin.users.delete_user import (
            DeleteUserUseCase,
        )

        uow.links.delete_by_owner.return_value = []
        service = Mock()
        service.delete_user.return_value = True
        use_case = DeleteUserUseCase(
            uow_factory=uow_factory,
            user_service=service,
            cache=Mock(),
            redirect_cache=Mock(),
            stats_cache=Mock(),
            logger=Mock(),
            audit_logger=audit,
        )

        use_case.execute(TARGET, context)

        audit.log_url_deleted.assert_not_called()
        audit.log_user_deleted.assert_called_once()

    def test_an_account_that_was_not_there_writes_no_record(
        self, uow, uow_factory, audit, context
    ):
        """``False`` means nothing was deleted, and a record would say
        otherwise."""
        from link_shortener.application.use_cases.admin.users.delete_user import (
            DeleteUserUseCase,
        )

        uow.links.delete_by_owner.return_value = []
        service = Mock()
        service.delete_user.return_value = False
        use_case = DeleteUserUseCase(
            uow_factory=uow_factory,
            user_service=service,
            cache=Mock(),
            redirect_cache=Mock(),
            stats_cache=Mock(),
            logger=Mock(),
            audit_logger=audit,
        )

        assert use_case.execute(TARGET, context) is False

        audit.log_user_deleted.assert_not_called()

    def test_a_deactivated_account_records_the_sessions_it_lost(
        self, uow, uow_factory, audit, context
    ):
        """Disabled while three sessions were open is a different situation
        from disabled while nobody held a token."""
        uow.refresh_sessions.revoke_all_for_user.return_value = 3
        service = Mock()
        service.deactivate_user.return_value = user_with()
        use_case = DeactivateUserUseCase(
            uow_factory=uow_factory,
            user_service=service,
            logger=Mock(),
            audit_logger=audit,
        )

        use_case.execute(TARGET, context)

        _, kwargs = audit.log_user_deactivated.call_args
        assert kwargs["target_user_id"] == TARGET
        assert kwargs["sessions_revoked"] == 3

    def test_a_reactivated_account_is_recorded(
        self, uow_factory, audit, context
    ):
        """The half that hands the access back."""
        service = Mock()
        service.activate_user.return_value = user_with()
        use_case = ActivateUserUseCase(
            uow_factory=uow_factory,
            user_service=service,
            logger=Mock(),
            audit_logger=audit,
        )

        use_case.execute(TARGET, context)

        assert audit.log_user_activated.call_args[1]["target_user_id"] == TARGET

    def test_an_address_confirmed_by_an_operator_is_recorded(
        self, uow_factory, uow, stored, audit, context
    ):
        """The bypass of the proof that an address belongs to anybody.

        It sits behind the same permission as suspension and deletion and
        does the same kind of thing -- it decides who may sign in -- so
        for a while it was the only one of them leaving no record. The
        comment saying why cited a port that carried nothing about
        accounts, which stopped being true the day the rest of this file
        was written.
        """
        account = user_with()
        account.email_verified = False
        stored[TARGET] = account
        uow.email_verifications.invalidate_for_user.return_value = 2
        use_case = ConfirmUserEmailUseCase(
            uow_factory=uow_factory, logger=Mock(), audit_logger=audit
        )

        use_case.execute(TARGET, context)

        written = audit.log_user_email_confirmed.call_args[1]
        assert written["target_user_id"] == TARGET
        assert written["already_confirmed"] is False

    def test_confirming_an_address_that_was_already_confirmed_says_so(
        self, uow_factory, uow, stored, audit, context
    ):
        """Pressing the button twice is not an error and is not a bypass
        either: the second press opened nothing that was shut."""
        account = user_with()
        account.email_verified = True
        stored[TARGET] = account
        uow.email_verifications.invalidate_for_user.return_value = 0
        use_case = ConfirmUserEmailUseCase(
            uow_factory=uow_factory, logger=Mock(), audit_logger=audit
        )

        use_case.execute(TARGET, context)

        assert audit.log_user_email_confirmed.call_args[1][
            "already_confirmed"
        ] is True


class TestARoleChangeOnAnAccountRecordsBothSides:
    """Which roles it held, and which it holds now."""

    @pytest.fixture
    def use_case(self, uow_factory, audit):
        service = Mock()
        service.update_roles.return_value = user_with("user", "admin")
        return UpdateUserRolesUseCase(
            uow_factory=uow_factory,
            user_service=service,
            logger=Mock(),
            audit_logger=audit,
        )

    def test_both_sides_reach_the_record(
        self, uow, stored, use_case, audit, context
    ):
        stored[TARGET] = user_with("user")
        uow.roles.get_by_name.side_effect = lambda name: role_granting(name)

        use_case.execute(TARGET, ["user", "admin"], context)

        _, kwargs = audit.log_roles_changed.call_args
        assert kwargs["roles_before"] == ["user"]
        assert kwargs["roles_after"] == ["user", "admin"]

    def test_the_previous_set_is_read_before_it_is_replaced(
        self, uow, stored, use_case, audit, context
    ):
        """"Now an administrator" and "was already one" are the same record
        with only the second half.

        Read after the write, ``roles_before`` would equal ``roles_after``
        and every promotion would look like a no-op.
        """
        stored[TARGET] = user_with("user")
        uow.roles.get_by_name.side_effect = lambda name: role_granting(name)

        use_case.execute(TARGET, ["user", "admin"], context)

        _, kwargs = audit.log_roles_changed.call_args
        assert kwargs["roles_before"] != kwargs["roles_after"]

    def test_an_account_that_held_nothing_is_recorded_as_holding_nothing(
        self, uow, use_case, audit, context
    ):
        """Not an error: the account may genuinely have had no roles, and
        the read must not invent one."""
        uow.roles.get_by_name.side_effect = lambda name: role_granting(name)

        use_case.execute(TARGET, ["admin"], context)

        assert audit.log_roles_changed.call_args[1]["roles_before"] == []


class TestRolesThemselvesAreRecorded:
    """The widest-reaching changes the administrative surface allows."""

    def test_a_created_role_is_recorded_with_what_it_grants(
        self, uow_factory, audit, context
    ):
        service = Mock()
        service.create_role.return_value = role_granting(
            "editor", "link:create", "link:delete_any"
        )
        use_case = CreateRoleUseCase(
            uow_factory=uow_factory,
            role_service=service,
            logger=Mock(),
            audit_logger=audit,
        )

        use_case.execute("editor", None, ["link:create"], context)

        _, kwargs = audit.log_role_created.call_args
        assert kwargs["role"] == "editor"
        assert kwargs["permissions"] == ["link:create", "link:delete_any"]

    def test_the_permissions_recorded_are_the_ones_the_role_ended_up_with(
        self, uow_factory, audit, context
    ):
        """A name the service did not resolve is not a permission this role
        grants, and recording the request would overstate what exists."""
        service = Mock()
        service.create_role.return_value = role_granting("editor", "link:create")
        use_case = CreateRoleUseCase(
            uow_factory=uow_factory,
            role_service=service,
            logger=Mock(),
            audit_logger=audit,
        )

        use_case.execute(
            "editor", None, ["link:create", "nonsense:invented"], context
        )

        assert audit.log_role_created.call_args[1]["permissions"] == [
            "link:create"
        ]

    def test_a_deleted_role_is_recorded(self, uow_factory, audit, context):
        """It takes its permissions off everyone who wore it."""
        use_case = DeleteRoleUseCase(
            uow_factory=uow_factory,
            role_service=Mock(),
            logger=Mock(),
            audit_logger=audit,
        )

        use_case.execute("editor", context)

        assert audit.log_role_deleted.call_args[1]["role"] == "editor"

    def test_changed_permissions_record_both_sides(
        self, uow, uow_factory, audit, context
    ):
        uow.roles.get_by_name.return_value = role_granting(
            "editor", "link:create"
        )
        service = Mock()
        service.update_role_permissions.return_value = role_granting(
            "editor", "link:create", "admin:all"
        )
        use_case = UpdateRolePermissionsUseCase(
            uow_factory=uow_factory,
            role_service=service,
            logger=Mock(),
            audit_logger=audit,
        )

        use_case.execute("editor", ["link:create", "admin:all"], context)

        _, kwargs = audit.log_role_permissions_changed.call_args
        assert kwargs["role"] == "editor"
        assert kwargs["permissions_before"] == ["link:create"]
        assert kwargs["permissions_after"] == ["link:create", "admin:all"]

    def test_the_previous_permissions_are_read_before_the_replacement(
        self, uow, uow_factory, audit, context
    ):
        """The question an investigator arrives with is what the role used
        to grant, and the new set alone cannot answer it."""
        uow.roles.get_by_name.return_value = role_granting("editor", "link:create")
        service = Mock()
        service.update_role_permissions.return_value = role_granting(
            "editor", "admin:all"
        )
        use_case = UpdateRolePermissionsUseCase(
            uow_factory=uow_factory,
            role_service=service,
            logger=Mock(),
            audit_logger=audit,
        )

        use_case.execute("editor", ["admin:all"], context)

        _, kwargs = audit.log_role_permissions_changed.call_args
        assert "link:create" in kwargs["permissions_before"]
        assert "link:create" not in kwargs["permissions_after"]


class TestNothingIsRecordedWhenNothingHappened:
    """A refusal is not a change, and must not read as one."""

    def test_a_failed_role_creation_writes_no_record(
        self, uow_factory, audit, context
    ):
        """The record would say a role exists that does not."""
        from link_shortener.domain import RoleAlreadyExistsError

        service = Mock()
        service.create_role.side_effect = RoleAlreadyExistsError("editor")
        use_case = CreateRoleUseCase(
            uow_factory=uow_factory,
            role_service=service,
            logger=Mock(),
            audit_logger=audit,
        )

        with pytest.raises(RoleAlreadyExistsError):
            use_case.execute("editor", None, ["link:create"], context)

        audit.log_role_created.assert_not_called()

    def test_a_failed_role_deletion_writes_no_record(
        self, uow_factory, audit, context
    ):
        from link_shortener.domain import RoleNotFoundError

        service = Mock()
        service.delete_role.side_effect = RoleNotFoundError("editor")
        use_case = DeleteRoleUseCase(
            uow_factory=uow_factory,
            role_service=service,
            logger=Mock(),
            audit_logger=audit,
        )

        with pytest.raises(RoleNotFoundError):
            use_case.execute("editor", context)

        audit.log_role_deleted.assert_not_called()
