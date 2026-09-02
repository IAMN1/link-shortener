"""The last administrator cannot be unmade through the role they wear.

The rule -- an operation must not leave the service with nobody holding
``admin:all`` -- stood on the three routes that act on an account and on
neither of the two that act on a role. Both reach the same end, and both
were measured against the running stack: an administrator moved onto a
role of their own making, then

* ``PUT /api/v1/admin/roles/<name>/permissions`` without ``admin:all``
  answered 200, and
* ``DELETE /api/v1/admin/roles/<name>`` answered 200, leaving the account
  holding no roles at all,

after which the admin API answered 403 to everybody and the surface could
only be recovered from a shell.

On an application of its own rather than the shared fixture: the question
is "is this the last administrator", and the shared database carries
whatever administrators other tests left in it -- which is how four tests
about the last administrator were once broken by a fifth.
"""

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.current_user_info import CurrentUserInfo
from link_shortener.domain import DomainError
from link_shortener.infrastructure.configs.app.testing import TestingConfig
from link_shortener.infrastructure.database.seed import seed_base_roles
from link_shortener.web.app_factory import create_app


PASSWORD = "S0le-Admin-Pass!"


ACTOR_EMAIL = "acting-administrator@example.test"


@pytest.fixture()
def application(tmp_path):
    """An application whose administrators are only the ones made here."""
    class OwnConfig(TestingConfig):
        TESTING = True
        SECRET_KEY = "last-admin-test-secret"
        SHORT_CODE_SECRET_PEPPER = "last-admin-test-pepper"
        DATABASE_URL = f"sqlite:///{tmp_path}/own.db"
        REDIS_ENABLED = False
        CACHE_ENABLED = False
        LOGGING_ENABLED = False
        AUDIT_ENABLED = False
        AUTO_SEED_ROLES = False
        BASE_URL = "http://testserver/"
        HOST = "testserver"
        PORT = 80

    built = create_app(config=OwnConfig())
    with built.app_context():
        db_manager = built.container.get_db_manager()
        db_manager.create_tables()
        with db_manager.session() as session:
            seed_base_roles(session)
        yield built


@pytest.fixture()
def service(application):
    """The admin facade of that application."""
    return application.container.get_admin_service()


@pytest.fixture()
def context(application):
    """A context standing for a real administrator of that application.

    Made through the same service the tests use, because the privilege
    rules read the actor from the database: a context naming nobody
    confers nothing, and ``admin:all`` cannot be handed out by nobody.
    """
    container = application.container
    with container.get_uow_factory()() as uow:
        actor = container.get_user_management_service().create_user(
            uow=uow,
            email=ACTOR_EMAIL,
            password=PASSWORD,
            roles=[uow.roles.get_by_name("admin")],
        )
        uow.commit()
        actor_id = actor.id

    return RequestContext(
        request_id="last-admin-test",
        remote_addr="127.0.0.1",
        user_agent="pytest",
        request_path="/",
        request_method="POST",
        current_user=CurrentUserInfo(
            id=actor_id, email=ACTOR_EMAIL, roles=["admin"], is_active=True
        ),
    )


def _move_the_only_administrator_onto(service, context, role_name):
    """Make a role granting ``admin:all`` the only thing conferring it.

    The acting administrator starts on the system ``admin`` role, which is
    what lets them create a role carrying ``admin:all`` at all -- nobody
    confers what they do not hold. They are then moved onto the new role
    and off ``admin``, which leaves that role the single reason anybody on
    this deployment is an administrator.

    Args:
        service: The admin facade.
        context: Request context of the acting administrator.
        role_name: Name for the role to create and move onto.
    """
    service.create_role(
        name=role_name,
        description="an administrator by another name",
        permission_names=["admin:all"],
        context=context,
    )
    service.update_user_roles(context.current_user.id, [role_name], context)


class TestTheRoleUnderTheLastAdministrator:
    """Neither route may take ``admin:all`` off the only one left."""

    def test_its_permissions_may_not_be_replaced(self, service, context):
        _move_the_only_administrator_onto(service, context, "owner")

        with pytest.raises(DomainError) as refusal:
            service.update_role_permissions(
                "owner", ["link:create"], context
            )

        assert refusal.value.code == "FORBIDDEN"

        # A refused operation writes nothing: the role still grants it.
        role = service.get_role("owner", context)
        assert "admin:all" in {p.name for p in role.permissions}

    def test_it_may_not_be_deleted(self, service, context):
        _move_the_only_administrator_onto(service, context, "owner")

        with pytest.raises(DomainError) as refusal:
            service.delete_role("owner", context)

        assert refusal.value.code == "FORBIDDEN"
        assert service.get_role("owner", context) is not None


class TestWhatTheGuardMustNotRefuse:
    """The count is a query, not a flag, and has to stay one."""

    def test_a_second_administrator_keeps_the_deletion_allowed(
        self, service, context
    ):
        """Through another role, so deleting this one costs the service
        nothing: the count is asked excluding the role, not the account."""
        _move_the_only_administrator_onto(service, context, "owner")
        service.create_user(
            email="second-administrator@example.test",
            password=PASSWORD,
            role_names=["admin"],
            context=context,
        )

        service.delete_role("owner", context)

        assert service.get_role("owner", context) is None

    def test_a_role_granting_nothing_administrative_is_untouched(
        self, service, context
    ):
        """The guard must not stand in front of ordinary role work."""
        _move_the_only_administrator_onto(service, context, "owner")
        service.create_role(
            name="editor",
            description="no administrative permission at all",
            permission_names=["link:create"],
            context=context,
        )

        service.delete_role("editor", context)

        assert service.get_role("editor", context) is None


class TestWhichRefusalComesFirst:
    """What is wrong with the request, before what is wrong with the state.

    Both refusals are true of ``{"roles": ["guest"]}`` aimed at the last
    administrator, and only one of them is actionable. "This would leave
    the service without an administrator" reads as "find another
    administrator and retry" -- and the retry is refused just the same,
    because no account may wear ``guest`` whatever the count says.

    The same ordering mistake was made once already, in `delete_role`:
    asking about the administrator count before the system-role flag made
    ``DELETE /admin/roles/admin`` answer two different ways depending on
    how many administrators existed, for a role that is never deletable.
    """

    def test_an_unassignable_role_is_refused_as_one(self, service, context):
        _move_the_only_administrator_onto(service, context, "owner")

        with pytest.raises(DomainError) as refusal:
            service.update_user_roles(
                context.current_user.id, ["guest"], context
            )

        assert refusal.value.code == "ROLE_NOT_ASSIGNABLE"

    def test_an_assignable_one_still_meets_the_count(self, service, context):
        """The guard behind it is untouched: ordinary roles still hit it."""
        _move_the_only_administrator_onto(service, context, "owner")

        with pytest.raises(DomainError) as refusal:
            service.update_user_roles(
                context.current_user.id, ["user"], context
            )

        assert refusal.value.code == "FORBIDDEN"


class TestTheSameQuestionOnBothRoutes:
    """``{"roles": ["guest"]}`` answers the same whoever asks it.

    Three answers were measured for one unanswerable request: an
    administrator creating an account got ``ROLE_NOT_ASSIGNABLE``, the
    same administrator replacing roles got ``ROLE_NOT_ASSIGNABLE``, and a
    caller holding only ``admin:manage_users`` creating an account got
    ``FORBIDDEN`` -- "You cannot grant permissions you do not hold
    yourself: link:create, stats:view_basic". The last reads as "obtain
    those two and retry", and no account may wear ``guest`` either way.
    """

    def _a_caller_who_only_manages_users(self, service, context):
        """A role holding ``admin:manage_users`` and nothing else, worn."""
        service.create_role(
            name="usermanager",
            description="manages accounts, holds nothing else",
            permission_names=["admin:manage_users"],
            context=context,
        )
        made = service.create_user(
            email="only-manages@example.test",
            password=PASSWORD,
            role_names=["usermanager"],
            context=context,
        )
        return RequestContext(
            request_id="ordering-test",
            remote_addr="127.0.0.1",
            user_agent="pytest",
            request_path="/",
            request_method="POST",
            current_user=CurrentUserInfo(
                id=made.id,
                email="only-manages@example.test",
                roles=["usermanager"],
                is_active=True,
            ),
        )

    def test_creating_an_account_says_the_role_is_unassignable(
        self, service, context
    ):
        manager = self._a_caller_who_only_manages_users(service, context)

        with pytest.raises(DomainError) as refusal:
            service.create_user(
                email="would-be-guest-2@example.test",
                password=PASSWORD,
                role_names=["guest"],
                context=manager,
            )

        assert refusal.value.code == "ROLE_NOT_ASSIGNABLE"

    def test_the_privilege_rule_behind_it_is_untouched(
        self, service, context
    ):
        """An assignable role the caller may not confer still refuses."""
        manager = self._a_caller_who_only_manages_users(service, context)

        with pytest.raises(DomainError) as refusal:
            service.create_user(
                email="would-be-admin@example.test",
                password=PASSWORD,
                role_names=["admin"],
                context=manager,
            )

        assert refusal.value.code == "FORBIDDEN"


class TestAMistypedPermissionIsAnsweredAsOne:
    """A name nothing carries is a missing permission, not a missing right.

    ``require_may_grant_permissions`` compares the request against what
    the caller holds, and a mistyped name is in neither -- so a caller
    holding only ``admin:manage_roles`` was told "You cannot grant
    permissions you do not hold yourself: link:craete" (measured), while
    an administrator was told "Permissions not found: link:craete". The
    first sends somebody looking for a way to obtain a permission that
    does not exist.
    """

    def _a_caller_who_only_manages_roles(self, service, context):
        """A role holding ``admin:manage_roles`` and nothing else, worn."""
        service.create_role(
            name="rolekeeper",
            description="manages roles, holds nothing else",
            permission_names=["admin:manage_roles"],
            context=context,
        )
        made = service.create_user(
            email="only-manages-roles@example.test",
            password=PASSWORD,
            role_names=["rolekeeper"],
            context=context,
        )
        return RequestContext(
            request_id="permission-ordering-test",
            remote_addr="127.0.0.1",
            user_agent="pytest",
            request_path="/",
            request_method="POST",
            current_user=CurrentUserInfo(
                id=made.id,
                email="only-manages-roles@example.test",
                roles=["rolekeeper"],
                is_active=True,
            ),
        )

    def test_creating_a_role_says_the_permission_is_missing(
        self, service, context
    ):
        keeper = self._a_caller_who_only_manages_roles(service, context)

        with pytest.raises(DomainError) as refusal:
            service.create_role(
                name="typo-role",
                description="names a permission that does not exist",
                permission_names=["link:craete"],
                context=keeper,
            )

        assert refusal.value.code == "PERMISSIONS_NOT_FOUND"

    def test_replacing_permissions_says_the_same(self, service, context):
        keeper = self._a_caller_who_only_manages_roles(service, context)
        service.create_role(
            name="editable",
            description="a role to rewrite",
            permission_names=["link:create"],
            context=context,
        )

        with pytest.raises(DomainError) as refusal:
            service.update_role_permissions(
                "editable", ["link:craete"], keeper
            )

        assert refusal.value.code == "PERMISSIONS_NOT_FOUND"

    def test_a_real_permission_the_caller_lacks_still_refuses(
        self, service, context
    ):
        """The privilege rule behind it is untouched."""
        keeper = self._a_caller_who_only_manages_roles(service, context)

        with pytest.raises(DomainError) as refusal:
            service.create_role(
                name="too-rich",
                description="names a real permission the caller lacks",
                permission_names=["admin:all"],
                context=keeper,
            )

        assert refusal.value.code == "FORBIDDEN"
