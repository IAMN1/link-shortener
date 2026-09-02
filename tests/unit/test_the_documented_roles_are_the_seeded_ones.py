"""The role table in the architecture chapter, against the file it describes.

`docs/architecture.md` prints a table of roles and then counts them in the
sentence below it: "the five above are system roles the service refuses to
change". The table had four rows. The missing one was `auditor` — the only
role that holds `audit:view`, which is the permission an administrator
deliberately does not have, and which two other documents rest on.

So a reader of the authorization chapter — the page every other document
points at for RBAC — could not learn that the role exists, while the same
page told them the list was complete. The sentence is what made it a
contradiction rather than an omission: a table headed "Key permissions"
may be a sample, a table counted as "the five above" may not.

Held against `configs/rbac/roles.yaml`, which is where the roles come
from, rather than against a list typed here — a list typed here would be a
third place to forget.
"""

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs/architecture.md"
RBAC = ROOT / "src/link_shortener/infrastructure/configs/rbac/roles.yaml"

TABLE_ROW = re.compile(r"^\|\s*`([a-z_]+)`\s*\|[^|]*\|[^|]*\|\s*$", re.MULTILINE)


def seeded_roles():
    """Every role the service seeds, from the file it seeds them out of."""
    config = yaml.safe_load(RBAC.read_text(encoding="utf-8"))
    return {role["name"] for role in config["roles"]}


def documented_roles():
    """Every role named in a row of the authorization table."""
    text = DOCS.read_text(encoding="utf-8")
    section = text.split("## Authorization (RBAC)", 1)
    assert len(section) == 2, (
        f"{DOCS} no longer has an '## Authorization (RBAC)' section; this "
        f"check reads the table under it"
    )
    return {found for found in TABLE_ROW.findall(section[1])}


class TestTheTableNamesEveryRoleTheServiceSeeds:

    def test_it_was_read_at_all(self):
        """
        A parser that matched nothing would let the comparison below pass
        over two empty sets.
        """
        assert len(documented_roles()) >= 5, documented_roles()
        assert len(seeded_roles()) >= 5, seeded_roles()

    def test_no_seeded_role_is_missing_from_the_table(self):
        missing = seeded_roles() - documented_roles()

        assert not missing, (
            f"{DOCS} does not name {sorted(missing)}, which the service "
            f"seeds. The page is the one every other document points at "
            f"for RBAC"
        )

    def test_no_documented_role_is_invented(self):
        """The other direction: a row for a role nothing seeds."""
        invented = documented_roles() - seeded_roles()

        assert not invented, (
            f"{DOCS} names {sorted(invented)}, which {RBAC.name} does not "
            f"seed"
        )

    def test_the_count_in_the_prose_matches_the_table(self):
        """
        The sentence under the table states a number, and that number is
        what turned a short table into a claim that it was complete.
        """
        text = DOCS.read_text(encoding="utf-8")
        spelled = {
            "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
        }
        counted = re.search(
            r"the (\w+) above are system roles", text
        )

        assert counted, "the sentence counting the roles is gone"
        assert spelled.get(counted.group(1)) == len(documented_roles()), (
            f"the prose says {counted.group(1)!r} and the table has "
            f"{len(documented_roles())} rows"
        )
