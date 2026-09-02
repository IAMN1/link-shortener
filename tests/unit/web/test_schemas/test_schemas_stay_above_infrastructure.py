"""No schema reads a fact out of the layer beneath the one it may know.

Two numbers put the web layer there. ``JournalQuery`` refused a ``limit``
above ``HARD_LIMIT`` and read it straight out of
``infrastructure.logging.journal_reader``; ``BatchCreateLinkRequest``
refused a longer list than ``MAX_BATCH_ITEMS`` and read that out of
``infrastructure.configs``. Both are now where a caller is entitled to read
them -- the journal's on its port, the batch's beside the DTOs of the
operation it bounds -- because a caller that must refuse an excess before
the work starts has to know what an excess is.

Written across the whole directory rather than about one module. It named
only ``journal.py`` while the batch was still reaching down, and said so:
a test wide enough to cover it would have had to name it as an exception,
and an exception in a rule is how a rule stops being one. There is no
exception left to name.
"""

import ast
import pathlib

import pytest

from link_shortener.application.dtos.batch import MAX_BATCH_ITEMS
from link_shortener.application.ports.journal_reader import HARD_LIMIT
from link_shortener.web.schemas.journal import JournalQuery
from link_shortener.web.schemas.requests import BatchCreateLinkRequest


SCHEMAS = pathlib.Path("src/link_shortener/web/schemas")


def modules():
    """Every schema module, so a new one is covered without being added here.

    Returns:
        The paths, sorted, so a failure names the same file every run.
    """
    return sorted(SCHEMAS.rglob("*.py"))


def imported_names(module: pathlib.Path) -> set:
    """Every module this one imports, as written.

    Read from the source rather than from ``sys.modules``: an import that
    happens to be satisfied by something already loaded is still an import,
    and it is the written line that has to be looked at.

    Args:
        module: The file to read.

    Returns:
        The dotted names of everything imported.
    """
    tree = ast.parse(module.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def test_there_are_schemas_to_check():
    """A directory that stopped being found would pass everything below."""
    assert len(modules()) > 1


@pytest.mark.parametrize("module", modules(), ids=lambda p: p.name)
def test_no_schema_reads_anything_out_of_infrastructure(module):
    reaching_down = {
        name for name in imported_names(module)
        if name.startswith("link_shortener.infrastructure")
    }

    assert reaching_down == set()


def test_the_journal_ceiling_it_refuses_by_is_the_port_s_own():
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


def test_the_batch_ceiling_it_refuses_by_is_the_application_s_own():
    """The same, for the number the batch request is bounded by."""
    with pytest.raises(ValueError):
        BatchCreateLinkRequest(urls=["https://example.com/"] * (MAX_BATCH_ITEMS + 1))

    accepted = BatchCreateLinkRequest(
        urls=["https://example.com/"] * MAX_BATCH_ITEMS
    )
    assert len(accepted.urls) == MAX_BATCH_ITEMS
