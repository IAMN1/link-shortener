"""Every administrative route refuses an ordinary user.

Written after a mutation run showed that seven working protections could be
deleted with the whole suite still green -- among them ``@require_permission``
on two admin endpoints. The unit tests could not catch it: their conftest
replaces the authorization service with a bare ``Mock()``, and a Mock answers
truthfully to anything, so the decorator is never exercised. The integration
tests covered privilege escalation but reached only the handful of endpoints
they were written for; ``activate`` and ``users/<id>/stats`` were called by
nothing at all.

So the guard is asserted against the route map rather than against a list.
A new administrative endpoint added without a permission decorator is a
failing test here, not a discovery in production -- the same arrangement the
project already uses for reserved short codes and for the OpenAPI document.
"""

import pytest

from tests.integration.conftest import auth_headers, register_and_login


ADMIN_PREFIX = "/api/v1/admin"

# Filled in for routes that take parameters. The values need not exist: an
# ordinary user must be refused before anything is looked up, and a 404 here
# would mean the check ran too late.
PARAMETERS = {
    "user_id": "00000000-0000-0000-0000-000000000000",
    "role_name": "no-such-role",
}

# Bodies for the verbs that require one. Never applied -- the request has to
# be refused first -- but a schema error would mask the missing guard.
BODIES = {
    "POST": {"email": "nobody@example.test", "password": "Irrelevant1!"},
    "PUT": {"permissions": []},
}


def admin_routes(app):
    """Return every administrative route, with its parameters filled in.

    Args:
        app: The application whose route map is read.

    Returns:
        List of (method, concrete path) pairs.
    """
    found = []
    for rule in app.url_map.iter_rules():
        if not str(rule).startswith(ADMIN_PREFIX):
            continue
        path = str(rule)
        for name, value in PARAMETERS.items():
            path = path.replace(f"<{name}>", value)
        if "<" in path:
            raise AssertionError(
                f"route {rule} has a parameter this test does not know how to "
                f"fill; add it to PARAMETERS so the route stays covered"
            )
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            found.append((method, path))
    return sorted(found)


@pytest.fixture(scope="module")
def routes(app):
    """Every administrative route in the application."""
    discovered = admin_routes(app)
    assert discovered, "no administrative routes found -- the prefix must be wrong"
    return discovered


class TestAdministrativeRoutesAreGuarded:
    """An ordinary account must not reach any of them."""

    def test_the_route_map_is_actually_being_read(self, routes):
        """Guards the guard: an empty list would make everything below pass."""
        paths = {path for _method, path in routes}
        assert f"{ADMIN_PREFIX}/users" in paths
        assert f"{ADMIN_PREFIX}/roles" in paths
        # The two the mutation run showed were called by nothing.
        assert any("/activate" in path for path in paths)
        assert any("/stats" in path for path in paths)

    def test_an_ordinary_user_is_refused_everywhere(self, app, routes):
        """403 on every administrative route, for a real logged-in user.

        Runs against the real authorization service and the real roles table,
        which is what the unit tests cannot do.
        """
        client = app.test_client()
        token = register_and_login(
            client, email="plain-user@guarded.test", password="Ordinary1!"
        )
        assert token, "the fixture user could not log in"
        headers = auth_headers(token)

        allowed = []
        for method, path in routes:
            response = client.open(
                path, method=method, headers=headers, json=BODIES.get(method)
            )
            # 403 is the answer. 401 would mean the user was not recognised,
            # which makes the test prove nothing about permissions.
            if response.status_code != 403:
                allowed.append(f"{method} {path} -> {response.status_code}")

        assert not allowed, (
            "administrative routes reachable by an ordinary user:\n  "
            + "\n  ".join(allowed)
        )

    def test_an_anonymous_client_is_refused_everywhere(self, app, routes):
        """No session at all must not be better than an ordinary one."""
        client = app.test_client()

        reachable = []
        for method, path in routes:
            response = client.open(path, method=method, json=BODIES.get(method))
            if response.status_code not in (401, 403):
                reachable.append(f"{method} {path} -> {response.status_code}")

        assert not reachable, (
            "administrative routes reachable without authentication:\n  "
            + "\n  ".join(reachable)
        )
