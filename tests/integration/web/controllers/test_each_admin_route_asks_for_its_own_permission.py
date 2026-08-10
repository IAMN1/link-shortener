"""
Every administrative route asks for its own permission, not merely some.

``test_every_admin_route_is_guarded`` asks whether an ordinary user is
refused everywhere, and it is. ``test_read_only_admin_cannot_write`` asks
whether a reader can write, and it cannot. Between them sat the question
neither asked: whether each route requires *the* permission it names, or
any administrative one that happens to be held.

It was the second, in two directions, both measured:

* ``admin:view_system_health`` swapped for ``admin:view_users`` on
  ``GET /api/v1/admin/health`` left the whole suite green -- the word
  ``view_system_health`` did not appear anywhere under ``tests/``. An
  account built to watch the queue depth could read every account on the
  service;
* ``admin:manage_users`` and ``admin:manage_roles`` were interchangeable
  on six of the eight writing routes. Measured on live requests with the
  swap in place: an account holding only ``admin:manage_roles`` created an
  account (201), deactivated one (200) and **deleted** one (200), taking
  its links with it -- while an account holding only ``admin:manage_users``
  was refused all three and could instead rewrite the permissions of any
  role.

So the check is a matrix rather than a list. Each of the five
administrative permissions is granted on its own, and every administrative
route is then asked whether it opens:

* the positive side names a concrete success code per permission, and asks
  the routes that take a parameter about something that exists -- a 404
  from a made-up id reads like a refusal, and a positive check that
  accepted it would pass on a route that had moved to another permission;
* the negative side is every remaining pair, and each must answer 403.

That is what OWASP asks for in A01 ("Except for public resources, deny by
default", A01:2021 and A01:2025 alike), one permission at a time.
"""

import pytest

from tests.integration.conftest import account_with_permissions, auth_headers


VICTIM = "00000000-0000-0000-0000-000000000000"
"""An id nothing answers to: a refusal must come before the lookup."""

# Every administrative route, filed under the permission meant to open it,
# with a body where the verb needs one. Written out rather than read off
# the decorators: a matrix built from the thing it checks agrees with
# itself no matter what either says.
ROUTES_OF = {
    "admin:view_users": [
        ("GET", "/api/v1/admin/users", None),
        ("GET", f"/api/v1/admin/users/{VICTIM}", None),
        ("GET", f"/api/v1/admin/users/{VICTIM}/stats", None),
    ],
    "admin:view_roles": [
        ("GET", "/api/v1/admin/roles", None),
        ("GET", "/api/v1/admin/roles/user", None),
    ],
    "admin:view_system_health": [
        ("GET", "/api/v1/admin/health", None),
    ],
    "admin:manage_users": [
        ("POST", "/api/v1/admin/users",
         {"email": "made@example.test", "password": "Irrelevant1!"}),
        ("PUT", f"/api/v1/admin/users/{VICTIM}/roles", {"roles": ["user"]}),
        ("POST", f"/api/v1/admin/users/{VICTIM}/deactivate", None),
        ("POST", f"/api/v1/admin/users/{VICTIM}/activate", None),
        ("DELETE", f"/api/v1/admin/users/{VICTIM}", None),
    ],
    "admin:manage_roles": [
        ("POST", "/api/v1/admin/roles",
         {"name": "made-by-a-writer", "permissions": ["link:create"]}),
        ("PUT", "/api/v1/admin/roles/user/permissions",
         {"permissions": ["link:create"]}),
        ("DELETE", "/api/v1/admin/roles/user", None),
    ],
}

# Every pair a permission must NOT open.
REFUSES = [
    (permission, method, path, body)
    for permission in ROUTES_OF
    for other, routes in ROUTES_OF.items()
    for method, path, body in routes
    if other != permission
]


def opens_for(permission, own_id):
    """
    Routes the permission must open, with the exact code each answers.

    Args:
        permission: The administrative permission under test.
        own_id: The account's own user id, used where a route takes one.

    Returns:
        List of (method, path, body, expected status).
    """
    catalogue = {
        "admin:view_users": [
            ("GET", "/api/v1/admin/users", None, 200),
            ("GET", f"/api/v1/admin/users/{own_id}", None, 200),
            ("GET", f"/api/v1/admin/users/{own_id}/stats", None, 200),
        ],
        "admin:view_roles": [
            ("GET", "/api/v1/admin/roles", None, 200),
            ("GET", "/api/v1/admin/roles/user", None, 200),
        ],
        "admin:view_system_health": [
            ("GET", "/api/v1/admin/health", None, 200),
        ],
        "admin:manage_users": [
            ("POST", "/api/v1/admin/users",
             {"email": "made-by-a-writer@example.test",
              "password": "Irrelevant1!"}, 201),
        ],
        "admin:manage_roles": [
            ("POST", "/api/v1/admin/roles",
             {"name": "made-by-a-role-writer", "permissions": ["link:create"]},
             201),
        ],
    }
    return catalogue[permission]


@pytest.fixture(scope="module")
def holders(app):
    """
    One logged-in account per administrative permission, holding that one.

    "That one" among the administrative permissions: registration also
    grants the default role, whose four permissions are about the caller's
    own links -- see ``account_with_permissions``, which measures them.
    ``test_every_admin_route_is_guarded`` is what holds that none of those
    four opens anything here.

    Module-scoped because each account costs a registration, a role and a
    login, and the tests that change anything do so under their own names.

    Args:
        app: The application under test.

    Returns:
        Mapping of permission name to (client, token, own user id).
    """
    accounts = {}
    for permission in ROUTES_OF:
        short = permission.split(":")[1]
        accounts[permission] = account_with_permissions(
            app,
            email=f"{short}@holder.test",
            password="HolderPass1!",
            role_name=f"only-{short}",
            permissions=[permission],
        )
    return accounts


class TestOnePermissionOpensItsOwnRoutes:

    @pytest.mark.parametrize("permission", sorted(ROUTES_OF))
    def test_the_permission_opens_what_it_is_for(self, holders, permission):
        """The premise: without it every refusal below could be an account
        whose token does not work at all.

        Args:
            permission: The one administrative permission the account holds.
        """
        client, token, own_id = holders[permission]

        answered = []
        for method, path, body, expected in opens_for(permission, own_id):
            response = client.open(
                path, method=method, json=body, headers=auth_headers(token)
            )
            if response.status_code != expected:
                answered.append(
                    f"{method} {path} -> {response.status_code} "
                    f"(wanted {expected}): {response.get_json()}"
                )

        assert not answered, (
            f"routes {permission} is supposed to open:\n  "
            + "\n  ".join(answered)
        )

    @pytest.mark.parametrize("permission, method, path, body", REFUSES)
    def test_it_opens_nothing_else(
        self, holders, permission, method, path, body
    ):
        """
        Args:
            permission: The one administrative permission the account holds.
            method: Verb of a route belonging to a different permission.
            path: That route's path.
            body: A body for the verbs that need one; never applied, since
                the request has to be refused before anything is parsed.
        """
        client, token, _own_id = holders[permission]

        response = client.open(
            path, method=method, json=body, headers=auth_headers(token)
        )

        assert response.status_code == 403, (
            f"{method} {path} answered {response.status_code} to an account "
            f"holding only {permission}: {response.get_json()}"
        )
        assert response.get_json()["error"] == "FORBIDDEN"

    def test_the_matrix_covers_every_administrative_route(self, app):
        """Guards the matrix: a route added without a line here would be
        checked by nothing, which is how ``/admin/health`` came to be
        checked by nothing.
        """
        listed = {
            (method, path)
            for routes in ROUTES_OF.values()
            for method, path, _body in routes
        }
        parameters = {"user_id": VICTIM, "role_name": "user"}

        found = set()
        for rule in app.url_map.iter_rules():
            path = str(rule)
            if not path.startswith("/api/v1/admin"):
                continue
            for name, value in parameters.items():
                path = path.replace(f"<{name}>", value)
            assert "<" not in path, (
                f"{rule} has a parameter this test cannot fill; add it to "
                f"the parameters above so the route stays covered"
            )
            for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
                found.add((method, path))

        assert found == listed
