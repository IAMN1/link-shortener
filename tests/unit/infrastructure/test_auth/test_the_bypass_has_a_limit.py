"""What ``admin:all`` carries, and the one thing it does not.

An administrator holds every power the audit journal exists to record, so a
bypass that handed them the record along with the powers would leave the
journal proving nothing about the caller it is chiefly kept against. The
service therefore refuses ``audit:view`` to the bypass and asks for the
permission itself -- which is what the ``auditor`` role is for.

What is checked here is the *limit*, from both sides: that the exception
holds, and that it did not quietly become a hole in the bypass generally.
Ordinary administrative work must go on passing, `logs:view` included --
`application.log` and `error.log` are what an operator reads to do the job,
and withholding those would be ceremony rather than separation of duties.
"""

import pytest

from link_shortener.domain import SystemPermissions
from link_shortener.domain.entities.permission import Permission
from link_shortener.domain.entities.role import Role
from link_shortener.domain.entities.user import User
from link_shortener.infrastructure.auth.rbac_authorization_service import (
    BEYOND_ADMIN_ALL, RBACAuthorizationService,
)


def permission(name: str) -> Permission:
    """A permission entity from its name alone.

    Args:
        name: The ``resource:action`` string.

    Returns:
        The entity, with the two halves of the name split back out.
    """
    resource, action = name.split(":", 1)
    return Permission(id=f"p-{name}", name=name, resource=resource, action=action)


def user_holding(*names: str) -> User:
    """A user carrying exactly the named permissions, through one role.

    Args:
        names: Permission names the user's role grants.

    Returns:
        The user entity.
    """
    role = Role(
        id="r-1",
        name="under-test",
        permissions=tuple(permission(name) for name in names),
    )
    return User.create(
        email="somebody@example.com",
        password_hash="not-checked-here",
        roles=[role],
    )


@pytest.fixture
def service():
    """The service under test.

    Neither collaborator is reached on the branches exercised here: the
    unit of work is opened only for anonymous callers, and nothing on
    these paths logs.
    """
    return RBACAuthorizationService(uow_factory=None, logger=None)


class TestTheAdministrativeBypass:

    def test_it_passes_ordinary_administrative_work(self, service):
        administrator = user_holding(SystemPermissions.ADMIN_ALL.value)

        assert service.is_allowed(
            administrator, SystemPermissions.ADMIN_MANAGE_USERS.value
        )
        assert service.is_allowed(
            administrator, SystemPermissions.ADMIN_VIEW_SYSTEM_HEALTH.value
        )
        assert service.is_allowed(
            administrator, SystemPermissions.LINK_DELETE_ANY.value
        )

    def test_it_passes_the_operational_journals(self, service):
        """`logs:view` is on the ordinary side of the line, deliberately.

        An operator reads `application.log` and `error.log` to do the job.
        The separation this module is about concerns the record kept
        *against* them, which is `audit.log` and nothing else.
        """
        administrator = user_holding(SystemPermissions.ADMIN_ALL.value)

        assert service.is_allowed(
            administrator, SystemPermissions.LOGS_VIEW.value
        )

    def test_it_does_not_pass_the_audit_journal(self, service):
        administrator = user_holding(SystemPermissions.ADMIN_ALL.value)

        assert not service.is_allowed(
            administrator, SystemPermissions.AUDIT_VIEW.value
        )

    def test_an_administrator_granted_the_permission_may_read(self, service):
        """The permission is what opens it, not the absence of the bypass.

        An administrator who also holds ``audit:view`` -- by taking the
        ``auditor`` role, which is the supported way -- passes. Without
        this the exception would be indistinguishable from a refusal that
        nothing can satisfy.
        """
        both = user_holding(
            SystemPermissions.ADMIN_ALL.value,
            SystemPermissions.AUDIT_VIEW.value,
        )

        assert service.is_allowed(both, SystemPermissions.AUDIT_VIEW.value)

    def test_the_exception_names_only_the_audit_journal(self):
        """The set itself, so that widening it is a deliberate act.

        Every name added here withdraws something from every administrator
        in every deployment, which is not a change to make by accident
        while editing a neighbouring line.
        """
        assert BEYOND_ADMIN_ALL == {SystemPermissions.AUDIT_VIEW.value}


class TestTheAuditorRole:
    """The role that reads the journals, seeded from ``roles.yaml``."""

    def test_it_opens_both_journals_and_the_health_report(self, service):
        auditor = user_holding(
            SystemPermissions.AUDIT_VIEW.value,
            SystemPermissions.LOGS_VIEW.value,
            SystemPermissions.ADMIN_VIEW_SYSTEM_HEALTH.value,
        )

        assert service.is_allowed(auditor, SystemPermissions.AUDIT_VIEW.value)
        assert service.is_allowed(auditor, SystemPermissions.LOGS_VIEW.value)
        assert service.is_allowed(
            auditor, SystemPermissions.ADMIN_VIEW_SYSTEM_HEALTH.value
        )

    @pytest.mark.parametrize("forbidden", [
        SystemPermissions.ADMIN_MANAGE_USERS.value,
        SystemPermissions.ADMIN_MANAGE_ROLES.value,
        SystemPermissions.LINK_DELETE_ANY.value,
        SystemPermissions.ADMIN_ALL.value,
    ])
    def test_it_grants_nothing_that_changes_anything(self, service, forbidden):
        """Read-only is the whole point, in the sense AU-9(6) asks for.

        A role that can read the record and also alter what the record is
        about is not a separation of duties; it is an administrator with
        an extra page.
        """
        auditor = user_holding(
            SystemPermissions.AUDIT_VIEW.value,
            SystemPermissions.LOGS_VIEW.value,
            SystemPermissions.ADMIN_VIEW_SYSTEM_HEALTH.value,
        )

        assert not service.is_allowed(auditor, forbidden)

    def test_reading_one_journal_does_not_open_the_other(self, service):
        """The two permissions are separate because the journals differ.

        `audit.log` holds destination addresses and the accounts that
        followed them; `application.log` holds the email address of
        everyone who registered or signed in. Somebody entitled to one is
        not thereby entitled to the other.
        """
        log_reader = user_holding(SystemPermissions.LOGS_VIEW.value)
        audit_reader = user_holding(SystemPermissions.AUDIT_VIEW.value)

        assert not service.is_allowed(
            log_reader, SystemPermissions.AUDIT_VIEW.value
        )
        assert not service.is_allowed(
            audit_reader, SystemPermissions.LOGS_VIEW.value
        )
