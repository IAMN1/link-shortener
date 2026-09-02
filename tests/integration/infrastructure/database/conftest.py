"""
Fixtures the two aggregate test files share.

``statements`` lives here rather than in either of them because both ask
the same question of their roll-up: does it cost one statement, or one per
row it writes? The visit half was measured first and the security half was
left un-measured, which is how it kept a read-and-write per row long after
the other stopped doing that.
"""

from contextlib import contextmanager

import pytest
from sqlalchemy import event


@pytest.fixture()
def statements(app):
    """
    Record the SQL a block of code sends, for counting round trips.

    Cost is the point of the checks that use this, and cost is not visible
    in a return value: a method folding the right numbers with one
    statement per row is correct and unusable.

    Returns:
        A context manager yielding the list the statements land in.
    """
    engine = app.container.get_db_manager().engine

    @contextmanager
    def recording():
        seen = []

        # The signature is SQLAlchemy's, not ours: `before_cursor_execute`
        # passes six positional arguments and this listener wants one of
        # them. Named rather than swallowed into `*args` so the callback
        # reads as the hook it implements. Suppressed here rather than in
        # `pyproject.toml`, whose `ignore-patterns` covers `test_*` and
        # leaves `conftest.py` measured -- widening that pattern would
        # quietly stop measuring every conftest in the suite.
        # pylint: disable=too-many-arguments,too-many-positional-arguments
        # pylint: disable=unused-argument
        def note(conn, cursor, statement, parameters, context, executemany):
            seen.append(statement)

        event.listen(engine, "before_cursor_execute", note)
        try:
            yield seen
        finally:
            event.remove(engine, "before_cursor_execute", note)

    with app.app_context():
        yield recording
