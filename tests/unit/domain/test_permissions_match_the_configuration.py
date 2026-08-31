"""That ``roles.yaml`` and ``SystemPermissions`` describe the same system.

Two lists of the same names, in two languages, and until now nothing
compared them. The enum is what the code checks against and what the admin
interface offers; the YAML is what a deployment is seeded from. They drift
in either direction and each drift fails differently:

  - a permission in the enum but not the YAML is a name the code guards a
    route with and no role can ever hold, so the route answers 403 to
    everybody and looks like a authorization bug;
  - a permission in the YAML but not the enum is granted to roles, stored
    in the database, shown in the interface as a checkbox -- and unknown to
    every ``require_permission`` in the application, so it guards nothing.

Neither shows up in a test of either file alone, which is why the two are
read here and compared as sets. Found while adding ``audit:view`` and
``logs:view``: nothing would have noticed had they been added to one file
and forgotten in the other.
"""

from pathlib import Path

import pytest
import yaml

from link_shortener.domain import SystemPermissions

ROLES_FILE = (
    Path(__file__).resolve().parents[3]
    / "src/link_shortener/infrastructure/configs/rbac/roles.yaml"
)


@pytest.fixture(scope="module")
def configuration() -> dict:
    """The seed configuration, parsed.

    Returns:
        The mapping ``roles.yaml`` holds.
    """
    return yaml.safe_load(ROLES_FILE.read_text(encoding="utf-8"))


class TestTheTwoListsAgree:

    def test_every_configured_permission_is_known_to_the_code(self, configuration):
        configured = {entry["name"] for entry in configuration["permissions"]}
        known = set(SystemPermissions.all_values())

        assert configured - known == set(), (
            "these are seeded and granted but no code can check them"
        )

    def test_every_permission_the_code_knows_is_configured(self, configuration):
        configured = {entry["name"] for entry in configuration["permissions"]}
        known = set(SystemPermissions.all_values())

        assert known - configured == set(), (
            "these are checked in code but no deployment can grant them"
        )


class TestTheRolesAreBuiltFromThoseNames:

    def test_no_role_grants_a_permission_that_does_not_exist(self, configuration):
        """A typo in a role's list is silent otherwise.

        The loader takes the names it recognises and passes over the rest,
        so ``audit:veiw`` costs a role its permission and says nothing.
        """
        declared = {entry["name"] for entry in configuration["permissions"]}

        for role in configuration["roles"]:
            granted = set(role.get("permissions", []))
            assert granted <= declared, (
                f"role {role['name']} grants {granted - declared}, "
                "which is declared nowhere"
            )

    def test_the_auditor_reads_and_does_not_write(self, configuration):
        """The role as configured, not as intended.

        Its whole value is that it can be handed to somebody who should see
        the record without being able to touch what the record is about, so
        an added ``admin:manage_*`` or any writing ``link:`` permission
        would empty it of meaning while leaving the name in place.

        Held as that property rather than as an exact set. Pinned to three
        names, this check refused a change made for a measured reason --
        the role saw *less than nobody*: `GET /api/v1/stats` and both visit
        endpoints answered 200 to an anonymous caller and 403 to a
        signed-in auditor, because `guest` holds `stats:view_basic` and
        this role held no statistics permission at all. What must not
        change is that everything here reads.
        """
        auditor = next(
            role for role in configuration["roles"] if role["name"] == "auditor"
        )
        granted = set(auditor["permissions"])

        must_have = {
            SystemPermissions.AUDIT_VIEW.value,
            SystemPermissions.LOGS_VIEW.value,
            SystemPermissions.ADMIN_VIEW_SYSTEM_HEALTH.value,
        }
        assert must_have <= granted, (
            f"the auditor no longer reads {sorted(must_have - granted)}, "
            f"which is what the role is for"
        )

        writes = {
            name for name in granted
            if any(
                verb in name
                for verb in ("manage", "create", "delete", "update", "all")
            )
        }
        assert not writes, (
            f"the auditor grants {sorted(writes)}, which touches what the "
            f"record is about"
        )

        assert auditor["is_system"] is True

    def test_every_signed_in_role_reads_what_an_anonymous_caller_reads(
        self, configuration
    ):
        """
        The property the auditor broke, stated over all of them.

        `guest` is what an unauthenticated visitor acts under, so what it
        may *read* is the floor of the service: a role below it refuses its
        holder something they could have had by signing out. Measured
        before this: `GET /api/v1/stats` and both visit endpoints answered
        200 with no token and 403 to a signed-in auditor.

        Reading only, and that narrowness is the finding rather than a
        convenience. `analyst` deliberately does not hold `link:create`
        while `guest` does -- it is a reading role, and the landing page
        says so in as many words: "This account may look links up, but not
        create them." Doing less than an anonymous caller is a decision
        this project makes on purpose; seeing less than one was not.

        `admin` passes on `admin:all`, which the authorization service
        treats as passing every check.
        """
        writing = ("manage", "create", "delete", "update", "all")

        def reads_only(permissions):
            return {
                name for name in permissions
                if not any(verb in name for verb in writing)
            }

        roles = {
            role["name"]: set(role.get("permissions", []))
            for role in configuration["roles"]
        }
        floor = reads_only(roles["guest"])
        assert floor, (
            "the guest role reads nothing; this check would hold nothing"
        )

        for name, granted in roles.items():
            if name == "guest" or SystemPermissions.ADMIN_ALL.value in granted:
                continue
            assert floor <= granted, (
                f"role {name} is refused {sorted(floor - granted)}, which "
                f"an anonymous caller may read"
            )

    def test_the_administrator_is_still_one_permission(self, configuration):
        """And that permission is not the audit journal's.

        ``admin:all`` is what the privilege guard counts to refuse the
        removal of the last administrator, so the role gaining a second
        entry is a change with consequences elsewhere.
        """
        admin = next(
            role for role in configuration["roles"] if role["name"] == "admin"
        )

        assert admin["permissions"] == [SystemPermissions.ADMIN_ALL.value]
