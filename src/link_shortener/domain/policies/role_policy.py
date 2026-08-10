"""
Rules for what a role may be called.

A role name is not only a label: it is the last segment of the URL every
route that acts on one role is reached through
(``/api/v1/admin/roles/<role_name>``). Werkzeug's default converter
"accepts any string but only one path segment. Thus the string can not
include a slash" -- so a name with a slash in it names a role no route can
address. Measured: ``POST`` created ``role/with/slash`` and answered 201,
and ``DELETE`` on it answered 404 while an ordinary role in the same run
deleted with 200. The role was reachable by nothing and removable by
nothing short of SQL.

Only the slash actually breaks the route. Measured against the live
routes with the pattern removed: ``role/with/slash`` and ``../admin``
create with 201 and answer 404 on both ``GET`` and ``DELETE``, while
``bad\\nname``, ``role with space``, a name of two spaces, ``..`` and
``%2e%2e`` create *and* delete with 200. The rest of the set is refused
on its own grounds -- a newline travels into every log line written about
the role, a name of only spaces is indistinguishable from another in any
list, and ``..`` reads as a traversal to whoever joins it onto a path
next.

Stated as what is allowed rather than as what is not: "Allowlist
validation involves defining exactly what IS authorized, and by
definition, everything else is not authorized" (OWASP Input Validation
Cheat Sheet, which calls allowlisting "the more robust and secure
approach" and leaves a denylist the smaller role of "an additional layer
of defense"). The four names this application ships -- ``guest``,
``user``, ``analyst``, ``admin`` -- are inside it.
"""


ROLE_NAME_MIN_LENGTH = 2
"""Shortest role name the service accepts, in characters."""

ROLE_NAME_MAX_LENGTH = 50
"""
Longest role name the service accepts, in characters.

Matches the ``roles.name`` column. Without it the schema accepted names
the database would not: measured on PostgreSQL 15, 51 characters into
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

ROLE_DESCRIPTION_MAX_LENGTH = 255
"""
Longest role description the service accepts, in characters.

Matches the ``roles.description`` column, for the reason
``ROLE_NAME_MAX_LENGTH`` gives. Measured on PostgreSQL 15: 256 characters
into ``VARCHAR(255)`` raise ``StringDataRightTruncation``, which a request
meets as a 500. SQLite does not check the width at all, so the suite alone
would never have shown it.
"""
