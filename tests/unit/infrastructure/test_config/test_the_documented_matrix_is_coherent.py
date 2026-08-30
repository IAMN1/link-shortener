"""
The table of ways to arrange this stack, held against its own rule.

``docs/getting-started.md`` publishes five arrangements: where the
application runs, where each dependency runs, which compose profiles are
on and which settings go with them. The rule the table states is that a
profile and a switch are two different statements and both have to be
made -- a profile brings a service up, a switch tells the application to
use one.

That rule is not decoration. Breaking it is what made the table necessary:
the single configuration template said ``COMPOSE_PROFILES=db,cache,broker``
and ``DATABASE_TYPE=sqlite`` on the same page, and following it brought up
PostgreSQL and two Redis while the application went past all three. The
migration wrote a schema inside its own container and exited 0, the
application opened an empty SQLite file beside it, ``/health`` answered
``healthy`` and the landing page answered ``500 no such table: roles``.

So the document is parsed rather than trusted. Every row is checked for:

* profiles that bring a service up while the switch beside them is off --
  a container running for nobody;
* switches that are on with neither their profile nor an address named --
  the application told to use a service that nothing provides;
* setting names that do not exist in ``.env.example``, which is the
  exhaustive list every other document points at.

What this cannot check: whether a row actually works. That is what the
live runs are for. What it can check is that a row cannot contradict
itself, which is the failure that happened.
"""

import re
from pathlib import Path

import pytest


DOCS = Path("docs/getting-started.md")
TEMPLATE = Path(".env.example")

HEADING = "## Choosing where each part runs"

# | # | Application | Its dependencies | `COMPOSE_PROFILES` | Settings | Also name |
ROW = re.compile(
    r"^\|\s*(?P<number>\d+)\s*\|"
    r"(?P<application>[^|]*)\|"
    r"(?P<dependencies>[^|]*)\|"
    r"(?P<profiles>[^|]*)\|"
    r"(?P<settings>[^|]*)\|"
    r"(?P<also>[^|]*)\|\s*$"
)

# What a profile brings up, and the switch that has to agree with it.
PROFILE_SWITCH = {
    "db": ("DATABASE_TYPE", "postgresql"),
    "cache": ("REDIS_ENABLED", "true"),
    "broker": ("CELERY_ENABLED", "true"),
}

# A switch that is on with its profile off has to name one of these
# instead. `DATABASE_HOST` counts for the database: naming the host is how
# row 2 reaches the stack's own PostgreSQL from outside the network.
ADDRESS_FOR = {
    "DATABASE_TYPE": ("DATABASE_URL", "DATABASE_HOST"),
    "REDIS_ENABLED": ("REDIS_URL",),
    "CELERY_ENABLED": ("CELERY_BROKER_URL",),
}


def _matrix_rows():
    """Every row of the arrangement table, parsed."""
    text = DOCS.read_text(encoding="utf-8")
    assert HEADING in text, (
        f"{DOCS} no longer has the section {HEADING!r}. The README links "
        f"to its anchor; a renamed heading is a broken link there."
    )

    body = text.split(HEADING, 1)[1]
    rows = []
    for line in body.splitlines():
        found = ROW.match(line)
        if not found:
            # The table ends at the first line that is not one of its rows.
            if rows:
                break
            continue
        rows.append(found)
    return rows


def _named(cell: str) -> dict[str, str]:
    """Settings named in a cell: `NAME=value` pairs, and bare names."""
    out = {}
    for token in re.findall(r"`([A-Z][A-Z0-9_]*)(?:=([^`]*))?`", cell):
        name, value = token
        out[name] = value
    return out


def _profiles(cell: str) -> list[str]:
    """The profiles a cell turns on. An italic *(empty)* means none."""
    if "empty" in cell:
        return []
    inside = re.search(r"`([^`]*)`", cell)
    if not inside:
        return []
    return [p.strip() for p in inside.group(1).split(",") if p.strip()]


ROWS = _matrix_rows()


class TestTheTableIsThere:

    def test_the_section_has_rows(self):
        # A regex that silently matches nothing would make every test
        # below pass over an empty list, which is the shape of a check
        # that confirms itself.
        assert len(ROWS) >= 5, (
            f"parsed {len(ROWS)} rows out of {DOCS}; the table documents "
            f"five arrangements, so either it shrank or the parser stopped "
            f"matching its shape"
        )


@pytest.mark.parametrize(
    "row", ROWS, ids=[f"row-{r['number']}" for r in ROWS]
)
class TestEveryRowAgreesWithItself:

    def test_a_profile_that_is_on_has_its_switch_on(self, row):
        settings = _named(row["settings"])
        for profile in _profiles(row["profiles"]):
            if profile not in PROFILE_SWITCH:
                continue
            name, expected = PROFILE_SWITCH[profile]
            assert settings.get(name) == expected, (
                f"row {row['number']} turns on the {profile!r} profile, "
                f"which brings a service up, and sets {name}="
                f"{settings.get(name)!r}, which tells the application not "
                f"to use one. That is a container running for nobody -- "
                f"and with {profile!r} it is the exact pair that reported "
                f"a healthy stack serving 500s."
            )

    def test_a_switch_that_is_on_has_a_service_behind_it(self, row):
        settings = _named(row["settings"])
        profiles = _profiles(row["profiles"])
        also = _named(row["also"])

        for profile, (name, on) in PROFILE_SWITCH.items():
            if settings.get(name) != on or profile in profiles:
                continue
            addresses = ADDRESS_FOR[name]
            assert any(a in also or a in settings for a in addresses), (
                f"row {row['number']} sets {name}={on} without the "
                f"{profile!r} profile, so nothing in this stack provides "
                f"that service, and names none of {addresses} to say where "
                f"it is."
            )

    def test_a_host_application_is_told_where_its_services_are(self, row):
        # A second rule, and the one a mutation probe found missing: the
        # profile being on is enough for a containerised application,
        # because compose writes `DATABASE_HOST: db` and the Redis URLs
        # into the container's environment. An application on the host
        # gets none of that -- it reads the env file and nothing else --
        # so every dependency it uses has to be named there, profile or
        # no profile. Dropping `REDIS_URL` from the row that runs the
        # application on the host left the table describing a setup whose
        # cache is unreachable, and the rule above passed it.
        if "host" not in row["application"].lower():
            return

        settings = _named(row["settings"])
        also = _named(row["also"])

        for name, on in PROFILE_SWITCH.values():
            if settings.get(name) != on:
                continue
            addresses = ADDRESS_FOR[name]
            assert any(a in also or a in settings for a in addresses), (
                f"row {row['number']} runs the application on the host "
                f"with {name}={on}, and names none of {addresses}. On the "
                f"host the service is reached by the address in the env "
                f"file; the compose network's names exist only inside it."
            )

    def test_every_setting_named_exists_in_the_template(self, row):
        declared = set(
            re.findall(
                r"^#?\s*([A-Z][A-Z0-9_]*)=",
                TEMPLATE.read_text(encoding="utf-8"),
                re.MULTILINE,
            )
        )
        named = set(_named(row["settings"])) | set(_named(row["also"]))
        invented = sorted(named - declared)
        assert not invented, (
            f"row {row['number']} names {invented}, which {TEMPLATE} does "
            f"not declare. {TEMPLATE} is the exhaustive list every "
            f"document points at, so a setting named only here is one a "
            f"reader cannot look up."
        )


class TestTheArrangementThatBrokeIsUnwritable:
    """
    The specific pair, called out because it is the reason for all of the
    above rather than one case among five.
    """

    def test_no_row_brings_up_postgresql_and_uses_sqlite(self):
        for row in ROWS:
            settings = _named(row["settings"])
            if "db" in _profiles(row["profiles"]):
                assert settings.get("DATABASE_TYPE") != "sqlite", (
                    f"row {row['number']} is the combination that started "
                    f"this: PostgreSQL in a container, the application on "
                    f"SQLite, both healthy, nothing served."
                )
