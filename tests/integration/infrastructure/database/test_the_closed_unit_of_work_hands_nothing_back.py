"""What a unit of work answers once its context has closed.

Entering builds nine repositories on one session; leaving closes that
session. Every accessor is written to refuse afterwards -- the guard is
``if self._x is None: raise RuntimeError`` -- and that refusal is only
as good as the clearing in ``__exit__``, which is a list of assignments
somebody has to remember to extend.

Somebody did not: ``_security_events`` was built at line 118 and left
out of the eight clears below. Measured before the fix -- eight
accessors refused, ``security_events`` handed back a
``SQLAlchemySecurityEventRepository`` bound to the closed session. A
write through it opens a transaction nobody commits, so the event is
dropped without a sound, in the one journal whose whole purpose is to
have no silences in it.

Written against the accessors as *discovered* rather than as a list
copied from the class: a tenth repository added later is covered here
without anybody remembering this file, which is precisely the kind of
remembering that failed the first time.
"""

import pytest

from link_shortener.infrastructure.database.unit_of_work import (
    SQLAlchemyUnitOfWork
)


def repository_accessors():
    """
    Every repository property the unit of work publishes.

    Returns:
        Sorted names of the properties that hand back a repository.
    """
    return sorted(
        name for name in dir(SQLAlchemyUnitOfWork)
        if not name.startswith("_")
        and isinstance(getattr(SQLAlchemyUnitOfWork, name, None), property)
        and name.endswith(("s", "events"))
        and name not in {"session"}
    )


@pytest.fixture()
def closed_uow(app):
    """A unit of work that has been entered and left again."""
    uow = SQLAlchemyUnitOfWork(app.container.get_db_manager())
    with uow:
        pass
    return uow


class TestEveryAccessorRefusesAfterTheContextCloses:

    def test_the_accessors_were_actually_found(self):
        """
        The check above this one is a loop over a discovered list, and a
        discovery that finds nothing passes such a loop in silence.
        """
        found = repository_accessors()

        assert len(found) >= 9, found
        assert "security_events" in found, found

    @pytest.mark.parametrize("name", repository_accessors())
    def test_it_refuses(self, closed_uow, name):
        """
        The session is closed; handing back a repository bound to it
        offers a write that goes nowhere.
        """
        with pytest.raises(RuntimeError, match="not entered"):
            getattr(closed_uow, name)

    def test_the_repositories_are_there_while_the_context_is_open(self, app):
        """
        The other half: the refusal must be about the context having
        closed, not about the accessors being broken outright.
        """
        uow = SQLAlchemyUnitOfWork(app.container.get_db_manager())

        with uow:
            for name in repository_accessors():
                assert getattr(uow, name) is not None
