"""A status a route actually answers with is a status the document declares.

``test_documented_responses_match`` checks the other direction and only for
successes: that every documented 2xx describes a body. Nothing checked that
the refusals a route makes are in the document at all, so a new answer
reached clients while the contract still described the old set -- which is
what happened here: ``ROLE_NOT_ASSIGNABLE`` began coming back 400 from two
account routes, and ``FORBIDDEN`` began coming back from the two role
routes when the change would leave the service without an administrator,
while the document said "Malformed body" and "The caller does not hold
admin:manage_roles".

The descriptions are prose and no test can hold them true. The status codes
are not, and an undeclared one is a generated client with no branch for it.

What this cannot check: ``_add_cross_cutting_responses`` folds 403 into
every state-changing operation and 429 into all of them, so those two are
declared whatever an operation says. A test asserting them would pass on
an empty document -- so this sweeps whatever the routes actually answer
and lets the merge cover what it covers.
"""

import pytest

from link_shortener.web.schemas.openapi import build_openapi


API_PREFIX = "/api/v1"

# The same fill-ins the envelope sweep uses; the values need not exist,
# because an anonymous caller is refused before anything is looked up.
PARAMETERS = {
    "user_id": "00000000-0000-0000-0000-000000000000",
    "role_name": "no-such-role",
    "short_code": "nosuch",
    "journal": "application",
}

BODIES = {
    "POST": {"email": "declared@example.test", "password": "Irrelevant1!"},
    "PUT": {"permissions": []},
    "PATCH": {},
}


def _documented(document, path, verb):
    """Return the status codes the document declares for one operation."""
    operations = document["paths"].get(path, {})
    operation = operations.get(verb.lower())
    return set(operation["responses"]) if operation else None


@pytest.fixture(scope="module")
def document():
    """The published document, built the way the route serves it."""
    return build_openapi("https://short.link")


class TestEveryAnswerAnAnonymousCallerGets:
    """Swept from the route map, so a new endpoint is covered by existing code."""

    def test_each_status_is_declared(self, app, client, document):
        undeclared = []
        checked = 0

        for rule in app.url_map.iter_rules():
            template = str(rule)
            if not template.startswith(API_PREFIX):
                continue
            concrete = template
            for name, value in PARAMETERS.items():
                concrete = concrete.replace(f"<{name}>", value)
                concrete = concrete.replace(f"<path:{name}>", value)
            if "<" in concrete:
                continue

            for verb in sorted(rule.methods - {"HEAD", "OPTIONS"}):
                declared = _documented(document, template, verb)
                if declared is None:
                    # Whether an operation is documented at all is the
                    # subject of test_api_docs; this test is about the
                    # statuses of the ones that are.
                    continue
                answer = client.open(
                    concrete, method=verb, json=BODIES.get(verb)
                )
                checked += 1
                if str(answer.status_code) not in declared:
                    undeclared.append(
                        f"{verb} {template} answered {answer.status_code}, "
                        f"declared {sorted(declared)}"
                    )

        assert checked >= 20, f"only {checked} operations were reached"
        assert undeclared == []
