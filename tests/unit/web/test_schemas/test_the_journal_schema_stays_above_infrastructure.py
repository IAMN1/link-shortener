"""The journal schema knows the ceiling without knowing who enforces it.

``JournalQuery`` refuses a ``limit`` above ``HARD_LIMIT``, and for a while
it read that number straight out of
``infrastructure.logging.journal_reader`` -- the web layer importing a fact
from the layer it is meant not to know. The number is now on the port, which
is where a caller is entitled to read it: the port is the contract both
sides agreed to, and the ceiling is part of it, since a caller that must
refuse an excess before the read has to know what an excess is.

Only this module is checked, not every schema. ``requests.py`` still reads
``MAX_BATCH_ITEMS`` out of ``infrastructure.configs``, which is the same
shape of fault about a different number -- and the batch is a slice of its
own. A test written wide enough to cover it would have to name it as an
exception, and an exception in a rule is how a rule stops being one.
"""

import ast
import pathlib

import pytest

from link_shortener.application.ports.journal_reader import HARD_LIMIT
from link_shortener.web.schemas.journal import JournalQuery


MODULE = pathlib.Path(
    "src/link_shortener/web/schemas/journal.py"
)


def imported_names() -> set:
    """Every module this schema imports, as written.

    Read from the source rather than from ``sys.modules``: an import that
    happens to be satisfied by something already loaded is still an import,
    and it is the written line that has to be looked at.

    Returns:
        The dotted names of everything imported.
    """
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def test_the_schema_reads_nothing_out_of_infrastructure():
    reaching_down = {
        name for name in imported_names()
        if name.startswith("link_shortener.infrastructure")
    }

    assert reaching_down == set()


def test_the_ceiling_it_refuses_by_is_the_port_s_own():
    """The point of the move: the same number, not a copy of it.

    A schema that kept its own ``2000`` would pass the test above and still
    be wrong the day the reader's ceiling moves -- the refusal would be
    about a limit nothing enforces.
    """
    with pytest.raises(ValueError):
        JournalQuery.model_validate({"limit": str(HARD_LIMIT + 1)})

    assert JournalQuery.model_validate({"limit": str(HARD_LIMIT)}).limit == (
        HARD_LIMIT
    )
