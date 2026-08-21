"""A security event is recorded after the transaction closes, never inside.

``CountingAuditLogger`` writes every security event to ``security_events``
as well as to the journal, and it does so in a transaction of its own --
deliberately, so that a failed count cannot roll back the work it was
recording. A caller that writes its event while its own unit of work is
still open therefore holds two connections at once: one committed but not
yet released, one taken from the pool to count with. On a deployment whose
workers are ``gunicorn --worker-class sync --workers 4`` that doubles the
pool an administrative action needs, for a row nobody is waiting on.

Seven use cases did it -- every role and account event but two -- while the
other six wrote after the block. Two spellings of one act, and the seven
were the expensive one.

The link events are outside the rule rather than exempted from it.
``COUNTED_ELSEWHERE`` names them: a redirect already writes to
``link_visits`` through a background task, so ``_count`` returns before
opening anything and there is no second connection to take. The set is read
here rather than restated, so that a link event moved out of it -- which is
what would make the second connection real -- reddens this test rather than
passing quietly.
"""

import ast
import pathlib

from link_shortener.infrastructure.logging.handlers.audit.counting import (
    COUNTED_ELSEWHERE,
)


USE_CASES = pathlib.Path("src/link_shortener/application/use_cases")

COUNTS_NOTHING = frozenset(
    f"log_{event.value.lower()}" for event in COUNTED_ELSEWHERE
)
"""The wrapper method belonging to each event that opens no transaction.

Derived from the vocabulary rather than typed out: ``URL_CREATED`` is
written by ``log_url_created``, and the two halves of that name are the
same fact spelled twice.
"""


def _opens_a_unit_of_work(node: ast.With) -> bool:
    """Whether this ``with`` is the one that opens a transaction.

    Args:
        node: The ``with`` statement to look at.

    Returns:
        ``True`` when any of its context managers is a unit-of-work factory.
    """
    for item in node.items:
        call = item.context_expr
        if not isinstance(call, ast.Call):
            continue
        called = getattr(call.func, "attr", getattr(call.func, "id", ""))
        if "uow_factory" in called:
            return True
    return False


def _audit_calls(node: ast.AST):
    """Every ``audit.log_*`` call anywhere inside a node.

    Args:
        node: Where to look.

    Yields:
        The call nodes.
    """
    for inner in ast.walk(node):
        if not isinstance(inner, ast.Call):
            continue
        if not isinstance(inner.func, ast.Attribute):
            continue
        if not inner.func.attr.startswith("log_"):
            continue
        if inner.func.attr == "log_security_event":
            # The method every wrapper funnels into. A use case calls a
            # wrapper; this name appearing here would be the port calling
            # itself, which is not what is being looked for.
            continue
        target = inner.func.value
        if getattr(target, "id", "") == "audit":
            yield inner


def written_inside_a_transaction():
    """Find every audit call made while a unit of work is open.

    Read from the source rather than by running the use cases: the point is
    a property of every one of them, including the ones a test would have to
    build a database for.

    Returns:
        ``(path, line, method)`` for each call inside an open transaction.
    """
    found = []
    for path in sorted(USE_CASES.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.With) and _opens_a_unit_of_work(node):
                for call in _audit_calls(node):
                    found.append((str(path), call.lineno, call.func.attr))
    return found


def test_no_security_event_is_written_from_an_open_transaction():
    offenders = [
        entry for entry in written_inside_a_transaction()
        if entry[2] not in COUNTS_NOTHING
    ]

    assert offenders == []


def test_the_rule_is_about_calls_that_would_open_a_second_transaction():
    """The set this test reads is the one ``_count`` actually consults.

    Without this, ``COUNTED_ELSEWHERE`` could be emptied -- making every
    link event open a transaction of its own -- and the test above would go
    on passing, because it would simply have no names left to excuse.
    """
    assert COUNTS_NOTHING, COUNTED_ELSEWHERE
    assert COUNTS_NOTHING == {
        "log_url_created", "log_url_accessed", "log_url_deleted"
    }
