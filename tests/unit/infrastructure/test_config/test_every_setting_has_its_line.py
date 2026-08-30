"""Every environment key ``src`` reads has its line in ``.env.example``.

``CONTRIBUTING.md`` says a new setting means a line in the template and
that a test fails if you skip it. There was no such test. What there was
instead is a template that had been called "the exhaustive list" in four
documents while one key it never listed was read on every start, and five
sessions of reading the two against each other by hand.

Reading them by hand is also how the two ways of missing a key were found,
and both are why this walks the syntax rather than the text:

* a declaration wraps -- ``env_int(`` on one line and the key on the next --
  so a pass matching line by line finds ``SECURITY_EVENT_RETENTION_DAYS``
  nowhere;
* a key reaches the call through a module constant
  (``os.environ.get(HANDOFF_ENV_VAR)``), so a pass looking for literals
  finds ``ALEMBIC_DATABASE_URL`` nowhere either.

Neither was caught by planting a wrong entry: the pass stayed silent and
agreed with a sentence naming one of them, which is the only reason anybody
looked. A pass that cannot say what it failed to read offers the same
"nothing found" for a hole as for a clean tree, so the reads whose key is
not a literal are counted here too, and the modules allowed to contain them
are named.
"""

import ast
import pathlib
from typing import Dict, List, Optional, Set, Tuple, TypeGuard

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[4]
SRC = PROJECT_ROOT / "src" / "link_shortener"
TEMPLATE = PROJECT_ROOT / ".env.example"

READERS = frozenset({
    "env_str", "env_int", "env_float", "env_bool", "env_list",
    "read_env", "read_env_for",
})
"""Names that read the environment by key. ``os.environ`` is handled apart."""

SECOND_ARGUMENT = frozenset({"read_env_for"})
"""Readers whose key is the second argument, the first being the config."""

KEY_IS_A_VARIABLE = frozenset({
    "infrastructure/configs/app/base.py",
    "infrastructure/configs/app/env.py",
    "infrastructure/configs/app/factory.py",
    "infrastructure/configs/app/migration_url.py",
    "infrastructure/configs/app/production.py",
    "infrastructure/configs/app/staging.py",
})
"""
Modules where a read may take its key from a variable.

These are the descriptor machinery and the file merge: the key is the
argument the caller passed, or a line of a ``.env`` file being published.
Anywhere else, a key that cannot be read here is a key this test cannot
answer for, and it says so rather than passing.
"""

READ_BUT_NOT_LISTED = frozenset({"FLASK_RUN_FROM_CLI"})
"""
The one key the template deliberately leaves out.

The ``flask`` command sets it in its own entry point to mark that it has
already merged ``.env`` into the environment; ``ConfigFactory`` reads it to
decide whether the files still need loading. Nobody sets it by hand, and
setting it under gunicorn or celery would have a variable the operator
exported treated as injected and overwritten by ``.env.<profile>``.

Written as an equality below, not as a subtraction: a line added to the
template for this key makes the set empty and reddens this test, so the
exception cannot outlive its reason.
"""


def _key_shaped(value: object) -> TypeGuard[str]:
    """Whether a constant looks like the name of an environment variable."""
    return (
        isinstance(value, str)
        and value.isupper()
        and value.replace("_", "").isalnum()
        and not value[0].isdigit()
    )


def _reads_the_environment(node: ast.Call) -> bool:
    """Whether this call reads a variable out of the environment."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in READERS
    if isinstance(func, ast.Attribute):
        if func.attr == "getenv":
            return True
        # os.environ.get(...)
        return (
            func.attr == "get"
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "environ"
        )
    return False


def _which_argument(node: ast.Call) -> int:
    """Which positional argument carries the key."""
    func = node.func
    name = func.id if isinstance(func, ast.Name) else ""
    return 1 if name in SECOND_ARGUMENT else 0


def _module_constants(tree: ast.AST) -> Dict[str, str]:
    """Constants assigned a key-shaped string, by the name they are bound to."""
    found: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets: List[ast.expr] = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue

        value = node.value
        if not isinstance(value, ast.Constant) or not _key_shaped(value.value):
            continue

        for target in targets:
            if isinstance(target, ast.Name):
                found[target.id] = value.value
    return found


def _walk_the_source() -> Tuple[Dict[str, List[str]], List[str]]:
    """Every key ``src`` reads, and every read whose key could not be read.

    Returns:
        A pair: keys mapped to the places that read them, and a list of
        places where the key is a variable this pass cannot resolve.
    """
    keys: Dict[str, List[str]] = {}
    unresolved: List[str] = []

    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text())
        constants = _module_constants(tree)
        where = path.relative_to(SRC).as_posix()

        for node in ast.walk(tree):
            key: Optional[str] = None
            if isinstance(node, ast.Call) and _reads_the_environment(node):
                index = _which_argument(node)
                if len(node.args) <= index:
                    continue
                argument = node.args[index]
            elif (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "environ"
            ):
                argument = node.slice
            else:
                continue

            if isinstance(argument, ast.Constant) and _key_shaped(argument.value):
                key = argument.value
            elif isinstance(argument, ast.Name) and argument.id in constants:
                key = constants[argument.id]

            if key is None:
                unresolved.append(f"{where}:{node.lineno}")
            else:
                keys.setdefault(key, []).append(f"{where}:{node.lineno}")

    return keys, unresolved


def _listed_in_the_template() -> Set[str]:
    """Every key the template names, commented-out lines included."""
    listed: Set[str] = set()
    for line in TEMPLATE.read_text().splitlines():
        stripped = line.strip().lstrip("#").strip()
        name, _, rest = stripped.partition("=")
        if rest is not None and _key_shaped(name.strip()):
            listed.add(name.strip())
    return listed


@pytest.fixture(scope="module")
def source():
    """The keys read and the reads that could not be resolved."""
    return _walk_the_source()


class TestTheTemplateIsTheListItSaysItIs:
    """``.env.example`` against what ``src`` actually reads."""

    def test_every_key_read_has_a_line_or_a_stated_reason(self, source):
        """A setting reaches the operator only if the template names it."""
        keys, _ = source
        missing = set(keys) - _listed_in_the_template()

        assert missing == set(READ_BUT_NOT_LISTED), "\n".join(
            f"{key}: {', '.join(keys[key])}"
            for key in sorted(missing.symmetric_difference(READ_BUT_NOT_LISTED))
        )

    def test_a_key_that_is_not_a_literal_stays_where_it_is_understood(self, source):
        """A read this pass cannot resolve is named, not passed over."""
        _, unresolved = source
        stray = [
            place for place in unresolved
            if place.rsplit(":", 1)[0] not in KEY_IS_A_VARIABLE
        ]

        assert stray == [], (
            "these reads take their key from a variable outside the modules "
            "where that is understood, so this test cannot answer for the "
            "keys they read: " + ", ".join(stray)
        )

    @pytest.mark.parametrize(
        "key, hidden_by",
        [
            ("SECURITY_EVENT_RETENTION_DAYS", "a declaration split over two lines"),
            ("ALEMBIC_DATABASE_URL", "a module constant holding the name"),
        ],
    )
    def test_the_two_ways_of_hiding_a_key_are_still_read(self, source, key, hidden_by):
        """The cases that defeated the pass before it walked the syntax.

        Neither is covered by the check above: both keys are listed in the
        template, so failing to read them leaves that check green, and both
        live in modules where an unread key is allowed -- so failing to read
        them leaves the second check green too. Losing either would put the
        count back where it was, quietly.
        """
        keys, _ = source

        assert key in keys, f"no longer read through {hidden_by}"

    def test_the_pass_reads_the_tree_it_is_pointed_at(self, source):
        """A pass that found nothing would agree with everything.

        The count is held well under what the tree carries, so ordinary
        growth does not touch it -- what it refuses is a walk that stopped
        finding anything at all, which is the shape every silent check
        takes.
        """
        keys, _ = source

        assert len(keys) > 60, f"only {len(keys)} keys found; the walk is broken"
        assert len(_listed_in_the_template()) > 60
