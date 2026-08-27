"""
Rules for what a role may be called.

A role name is not only a label: it is the last segment of the URL every
route that acts on one role is reached through
(``/api/v1/admin/roles/<role_name>``). Werkzeug's default converter
"accepts any string but only one path segment. Thus the string can not
include a slash" -- so a name with a slash in it names a role no route
can address: it is created, and then reachable by nothing and removable
by nothing short of SQL.

Only the slash actually breaks the route. The rest of what is refused is
refused on its own grounds -- a newline travels into every log line
written about the role, a name of only spaces is indistinguishable from
another in any list, and ``..`` reads as a traversal to whoever joins it
onto a path next.

Stated as what is allowed rather than as what is not: "Allowlist
validation involves defining exactly what IS authorized, and by
definition, everything else is not authorized" (OWASP Input Validation
Cheat Sheet, which calls allowlisting "the more robust and secure
approach" and leaves a denylist the smaller role of "an additional layer
of defense"). Every role name this application ships, in ``roles.yaml``,
is inside it.
"""

import re
from typing import Iterable, Optional, TYPE_CHECKING

from link_shortener.domain.exceptions import (
    RoleNotAssignableError, ValidationError
)
from link_shortener.domain.i18n import N_

if TYPE_CHECKING:  # pragma: no cover - imported for the annotation only
    from link_shortener.domain.entities.role import Role


GUEST_ROLE_NAME = "guest"
"""
Name of the role an unauthenticated caller acts under.

Here rather than beside the authorization service that reads it, because
it is not that service's fact: two rules turn on this name and only one of
them is about authorization. The other is that no account may be given it
-- a role meant for whoever has not signed in confers, on somebody who
has, the entitlements of a passer-by.
"""

ROLE_NAME_MIN_LENGTH = 2
"""Shortest role name the service accepts, in characters."""

ROLE_NAME_MAX_LENGTH = 50
"""
Longest role name the service accepts, in characters.

Matches the ``roles.name`` column. Without it the schema accepted names
the database would not: on PostgreSQL 15, 51 characters into
``VARCHAR(50)`` raise ``StringDataRightTruncation``, which the caller
meets as a 500 rather than as the 400 this application answers a bad
field with.

The width a deployed database actually has is written a third time, as a
literal in ``migrations/versions/0001_initial_schema.py`` -- that is the
file PostgreSQL is built from, while the ORM model only serves
``create_all`` on SQLite in tests. Widening this constant alone would
leave the column where it was, so the migration is read back in
``test_the_name_bound_is_the_width_the_migration_creates``.
"""

ROLE_NAME_PATTERN = r"^[A-Za-z0-9_-]+$"
"""
Characters a role name may be made of.

Letters, digits, underscore and hyphen: enough for every name in
``roles.yaml`` and for the ones an operator is likely to add, and short of
anything that has a meaning in a URL path.
"""

def require_roles_are_assignable(roles: Iterable["Role"]) -> None:
    """
    Check that every one of these roles may be worn by an account.

    ``guest`` may not. It is the role an unauthenticated request acts
    under, so an account wearing it holds what a passer-by holds: it signs
    in and the dashboard it lands on refuses it.

    Asked by ``User.create`` and by ``UserManagementService.update_roles``,
    which between them are every way a role reaches an account. It was
    first put in the service alone, on the reasoning that the API, the
    panel and both CLI commands all arrive there -- and registration does
    not: it builds the entity itself, so a deployment with
    ``DEFAULT_ROLE_NAME=guest`` registered guests, measured at 202 with
    the account holding ``guest``. The rule was in the callers again, and
    the third caller broke it again.

    Args:
        roles: The roles an account is about to be given.

    Raises:
        RoleNotAssignableError: At the first role no account may carry.
    """
    for role in roles:
        if role.name == GUEST_ROLE_NAME:
            raise RoleNotAssignableError(role.name)


def require_valid_role_name(name: str) -> None:
    """
    Refuse a role name the service cannot address or log.

    The rule itself was written twice already -- as these constants and as
    the Pydantic field built from them -- and that pairing is deliberate:
    the schema refuses malformed input at the edge with a field-level
    message. What it is not is the only place the rule is applied. Roles
    also arrive through ``flask db load-custom-roles``, which reads a YAML
    file and never meets the schema, and a name with a slash in it created
    that way is a role no route can address and nothing short of SQL can
    remove. Measured: ``a/b`` went in.

    Args:
        name: The name a role is about to be created under.

    Raises:
        ValidationError: If the name is outside what a role may be called.
    """
    if not isinstance(name, str) or not re.fullmatch(ROLE_NAME_PATTERN, name):
        raise ValidationError(
            N_(
                "A role name must be letters, digits, hyphen or underscore"
            ),
            field="name",
        )
    if not ROLE_NAME_MIN_LENGTH <= len(name) <= ROLE_NAME_MAX_LENGTH:
        raise ValidationError(
            f"A role name must be {ROLE_NAME_MIN_LENGTH} to "
            f"{ROLE_NAME_MAX_LENGTH} characters long",
            field="name",
            template=N_(
                "A role name must be %(least)s to %(most)s characters long"
            ),
            params={
                "least": ROLE_NAME_MIN_LENGTH,
                "most": ROLE_NAME_MAX_LENGTH,
            },
        )


ROLE_DESCRIPTION_MAX_LENGTH = 255
"""
Longest role description the service accepts, in characters.

Matches the ``roles.description`` column, for the reason
``ROLE_NAME_MAX_LENGTH`` gives. On PostgreSQL 15: 256 characters
into ``VARCHAR(255)`` raise ``StringDataRightTruncation``, which a request
meets as a 500. SQLite does not check the width at all, so the suite alone
would never have shown it.
"""


def require_valid_role_description(description: Optional[str]) -> None:
    """
    Refuse a role description the column cannot hold.

    The other half of ``require_valid_role_name``, and it was missing at
    the same door. The bound was stated twice -- as this constant and as
    the Pydantic field built from it -- and roles also arrive through
    ``flask db load-custom-roles``, which reads a YAML file and never
    meets the schema. Measured on the running stack: a 256-character
    description in that file came back as
    ``sqlalchemy.exc.DataError: (psycopg.errors.StringDataRightTruncation)
    value too long for type character varying(255)``, a traceback out of
    the driver, where the same file's ``a/b`` name is refused by name with
    a sentence saying what is wrong.

    Absent, ``None``, and empty are all allowed: the column is nullable
    and the admin API's schema defaults the field to ``""``.

    Anything that is not a string is refused rather than measured, the
    way ``require_valid_role_name`` refuses one. The YAML door is the
    reason both need it: a file may put anything at all under
    ``description``, and without this ``description: 123`` left by
    ``len()`` as a ``TypeError`` -- a traceback naming no field, which is
    the outcome this whole rule exists to replace -- while
    ``description: [a, b]`` measured four and went into the column.

    Args:
        description: The description a role is about to be created with.

    Raises:
        ValidationError: If it is not a string, or is longer than the
            column is wide.
    """
    if description is None:
        return
    if not isinstance(description, str):
        raise ValidationError(
            N_("A role description must be text"),
            field="description",
        )
    if len(description) > ROLE_DESCRIPTION_MAX_LENGTH:
        raise ValidationError(
            f"A role description must be at most "
            f"{ROLE_DESCRIPTION_MAX_LENGTH} characters long",
            field="description",
            template=N_(
                "A role description must be at most %(most)s characters long"
            ),
            params={"most": ROLE_DESCRIPTION_MAX_LENGTH},
        )
