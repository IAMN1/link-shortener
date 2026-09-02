"""
Tests that the audit journal records a change only when there was one.

The rule is the project's own, written down in `docs/decisions.md` about
`db load-custom-roles`: "Only where the set actually changed: running the
same file twice rewrites the same associations, and a record of that
reports a change nobody made." It stood at that door and at no other.

Measured on the running stack before this file: `PUT
/api/v1/admin/users/<id>/roles` with the roles the account already held
answered 200 and wrote `ROLES_CHANGED` with `roles_before: ['user']` and
`roles_after: ['user']`, and `PUT /api/v1/admin/roles/<name>/permissions`
did the same with its own set. The panel makes exactly that request: the
edit form sends every ticked checkbox on save, so an operator who opened
a form, changed nothing and saved left a record saying they had moved an
account's privileges.

That matters because of what the journal is for. An investigation reads
it to find who touched whose entitlements, and an entry that names an act
nobody performed is a false lead in the one place that must not have any.
"""

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.current_user_info import CurrentUserInfo
from link_shortener.domain import Role


PASSWORD = "Unchanged1!"
ACTOR = "unchanged-set-actor@example.test"

# Nobody confers what they do not hold, so the actor holds exactly what
# these tests hand out: the permissions behind the `user` and `analyst`
# roles, the two put into roles here, and the administrative rights to do
# the handing out.
ACTOR_MAY_CONFER = (
    "link:create",
    "link:view_own",
    "link:delete_own",
    "stats:view_basic",
    "stats:view_any",
    "stats:view_full",
    "admin:manage_users",
    "admin:manage_roles",
    "admin:view_users",
    "admin:view_roles",
)


@pytest.fixture(scope="module")
def admin(app):
    """
    The facade, and the context of an administrator acting through it.

    An actor is needed rather than a bare request id: handing out a role
    is checked against what the caller holds, so a context with nobody in
    it cannot grant `link:create` to anything. Built once for the module,
    because the application fixture is built once for the session and
    registering this address twice is registering it twice.

    Given exactly the permissions these tests hand out, and deliberately
    not `admin:all`. The suite's database is one for the whole session, so
    a second account holding `admin:all` is a second administrator for
    every other test too -- measured: with this actor on the `admin` role,
    the four checks in
    ``test_admin_privilege_escalation.py::TestTheLastAdministratorStays``
    failed, because the administrator they had just made was no longer the
    last one.
    """
    from sqlalchemy import text

    with app.app_context():
        container = app.container
        with container.get_uow_factory()() as uow:
            granted = uow.permissions.get_by_names(list(ACTOR_MAY_CONFER))
            actor_role = Role(
                id="unchanged-set-actor-role",
                name="unchanged-set-actor",
                description="what these tests hand out, and nothing more",
                is_system=False,
                permissions=tuple(granted),
            )
            uow.roles.save(actor_role)
            actor = container.get_user_management_service().create_user(
                uow=uow, email=ACTOR, password=PASSWORD, roles=[actor_role]
            )
            uow.commit()
            actor_id = actor.id

        yield (
            container.get_admin_service(),
            RequestContext(
                request_id="unchanged-set-test",
                current_user=CurrentUserInfo(
                    id=actor_id,
                    email=ACTOR,
                    roles=["unchanged-set-actor"],
                    is_active=True,
                ),
            ),
        )

        # The account and its role go with the module, so the rest of the
        # session sees the table it would have seen.
        with app.container.get_db_manager().session() as session:
            session.execute(
                text("DELETE FROM users WHERE email = :e"), {"e": ACTOR}
            )
            session.execute(
                text("DELETE FROM roles WHERE name = :n"),
                {"n": "unchanged-set-actor"},
            )
            session.commit()


@pytest.fixture()
def journal(app):
    """
    Counts the security events the application actually stored.

    Reads the table rather than intercepting the logger. The first
    version of this file patched ``log_security_event`` on the audit
    manager and counted the calls -- and counted none of them, because
    every use case binds its context first and writes through the bound
    copy, which the patch never touched. Both "nothing was written"
    checks passed on an empty list that would have been empty however
    the code behaved.
    """
    from sqlalchemy import text

    def count(event_type):
        with app.app_context():
            with app.container.get_db_manager().session() as session:
                return session.execute(
                    text(
                        "SELECT COUNT(*) FROM security_events "
                        "WHERE event_type = :t"
                    ),
                    {"t": event_type},
                ).scalar()

    return count


class TestAccountRoles:

    def test_replacing_the_roles_with_the_same_ones_writes_nothing(
        self, admin, journal
    ):
        service, context = admin
        made = service.create_user(
            "same-roles@example.test", PASSWORD, context, role_names=["user"]
        )
        before = journal("ROLES_CHANGED")

        service.update_user_roles(made.id, ["user"], context)

        assert journal("ROLES_CHANGED") == before, (
            "a record was written for a set that did not change"
        )

    def test_a_different_order_is_not_a_change_either(self, admin, journal):
        """The request names roles; it does not order them."""
        service, context = admin
        made = service.create_user(
            "order-only@example.test",
            PASSWORD,
            context,
            role_names=["user", "analyst"],
        )
        before = journal("ROLES_CHANGED")

        service.update_user_roles(made.id, ["analyst", "user"], context)

        assert journal("ROLES_CHANGED") == before

    def test_a_real_change_is_still_recorded(self, admin, journal):
        service, context = admin
        made = service.create_user(
            "real-change@example.test", PASSWORD, context, role_names=["user"]
        )
        before = journal("ROLES_CHANGED")

        service.update_user_roles(made.id, ["analyst"], context)

        assert journal("ROLES_CHANGED") == before + 1


class TestRolePermissions:

    def test_replacing_the_permissions_with_the_same_ones_writes_nothing(
        self, admin, journal
    ):
        service, context = admin
        service.create_role(
            "unchanged-role", "same set twice", ["link:create"], context
        )
        before = journal("ROLE_PERMISSIONS_CHANGED")

        service.update_role_permissions(
            "unchanged-role", ["link:create"], context
        )

        assert journal("ROLE_PERMISSIONS_CHANGED") == before

    def test_a_real_change_is_still_recorded(self, admin, journal):
        service, context = admin
        service.create_role(
            "changed-role", "a set that moves", ["link:create"], context
        )
        before = journal("ROLE_PERMISSIONS_CHANGED")

        service.update_role_permissions(
            "changed-role", ["link:view_own"], context
        )

        assert journal("ROLE_PERMISSIONS_CHANGED") == before + 1
