"""
What ``roles.yaml`` tells a reader the administrator can do, against what
``BEYOND_ADMIN_ALL`` lets them do.

``admin:all`` passes every permission check but one: ``audit:view`` is
held back, because the administrator is the caller the audit trail is
chiefly kept against. That exception is enforced in
``rbac_authorization_service.py`` and explained in a comment inside
``roles.yaml`` itself -- and three lines in the same file said the
opposite anyway:

    description: "Full administrative access – bypasses all permission checks"
    # Administrator role – has full control over the system.
    description: "System administrator with unrestricted access"

The descriptions are not comments. They are seeded into the ``roles`` and
``permissions`` tables, returned by ``GET /api/v1/admin/roles``, printed
by ``flask security list-roles`` and shown on the roles page -- so the
sentence a person reads before granting the role said the role had no
limit, while the service answered ``403`` to that role on the audit
journal. Measured on a live stack: ``GET /api/v1/journals/audit`` under an
administrator answers ``403``.

Held here rather than left to review because the two facts live in
different files and neither one is wrong on its own.
"""

from pathlib import Path

import pytest
import yaml

from link_shortener.infrastructure.auth.rbac_authorization_service import (
    BEYOND_ADMIN_ALL,
)


ROLES_FILE = (
    Path(__file__).resolve().parents[3]
    / "src/link_shortener/infrastructure/configs/rbac/roles.yaml"
)

QUALIFIERS = ("except", "apart from", "other than", "but not")
"""Ways of admitting a limit. A description claiming unrestricted power
has to carry one of these once ``BEYOND_ADMIN_ALL`` holds anything."""

ABSOLUTES = ("all permission checks", "unrestricted", "full control")
"""Ways of claiming there is no limit."""


@pytest.fixture(scope="module")
def configuration() -> dict:
    """The seed configuration, parsed."""
    return yaml.safe_load(ROLES_FILE.read_text(encoding="utf-8"))


def described(entries, name: str) -> str:
    """
    The description of one entry, by name.

    Args:
        entries: The ``permissions`` or ``roles`` list from the YAML.
        name: The entry to find.

    Returns:
        Its description.
    """
    for entry in entries:
        if entry["name"] == name:
            return entry["description"]
    raise AssertionError(f"{name} is not in roles.yaml any more")


class TestTheExceptionIsRealBeforeAnythingElse:

    def test_the_bypass_has_something_held_back(self):
        """
        If this ever empties, the descriptions below may say "all".

        The test is written the other way round on purpose: the checks
        that follow are only meaningful while there is an exception, and
        a reader arriving after it was removed should be told that here
        rather than left puzzling at a failure.
        """
        assert BEYOND_ADMIN_ALL, (
            "BEYOND_ADMIN_ALL is empty: admin:all now really does pass "
            "every check, and the descriptions this file guards may say so"
        )


class TestThePermissionDescription:

    def test_it_names_every_permission_held_back(self, configuration):
        """The one place a reader learns the limit is this sentence."""
        text = described(configuration["permissions"], "admin:all")

        missing = [p for p in BEYOND_ADMIN_ALL if p not in text]
        assert not missing, (
            f"admin:all is described without naming what it does not "
            f"carry: {missing}"
        )

    def test_it_does_not_claim_the_opposite(self, configuration):
        """An absolute claim needs a qualifier beside it."""
        text = described(configuration["permissions"], "admin:all").lower()

        if any(a in text for a in ABSOLUTES):
            assert any(q in text for q in QUALIFIERS), text


class TestTheRoleDescription:

    def test_it_does_not_claim_unrestricted_access(self, configuration):
        """
        This is the line ``flask security list-roles`` prints.

        It is also the line the roles page shows, and it is the shortest
        of the three -- which is why it is the one most likely to be read
        and the one that must not overstate.
        """
        text = described(configuration["roles"], "admin").lower()

        if any(a in text for a in ABSOLUTES):
            assert any(q in text for q in QUALIFIERS), text

    def test_a_reader_of_that_line_learns_there_is_a_limit(self, configuration):
        """Naming the limit, in whatever words, rather than only hinting."""
        text = described(configuration["roles"], "admin").lower()

        assert "audit" in text, (
            "the admin role's description does not mention the journal it "
            "cannot read"
        )
