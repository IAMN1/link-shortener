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

from link_shortener.application.ports.uow import UnitOfWork
from link_shortener.infrastructure.database.unit_of_work import (
    SQLAlchemyUnitOfWork
)


def repository_accessors():
    """
    Every repository property the unit of work publishes.

    Read off the **port**, which is the definition of what a unit of work
    hands back: every abstract property on ``UnitOfWork`` is a repository,
    and a tenth added there is covered here the moment it is declared.

    It used to be read off the implementation and filtered by
    ``name.endswith(("s", "events"))``, which is a guess about spelling
    rather than a question about the thing -- an accessor named ``audit``
    or ``link_dedup`` would have been skipped in silence while the count
    below still read nine, which is exactly the "somebody remembering this
    file" this file exists to avoid.

    Returns:
        Sorted names of the properties that hand back a repository.
    """
    return sorted(
        name for name, attribute in vars(UnitOfWork).items()
        if isinstance(attribute, property)
        and getattr(attribute.fget, "__isabstractmethod__", False)
    )


def implementation_only_properties():
    """Repository-shaped properties the implementation adds of its own.

    The other half of reading the port: a repository published by
    ``SQLAlchemyUnitOfWork`` and not declared on ``UnitOfWork`` would be
    invisible to the list above. ``session`` is the one property that is
    not a repository and is named here rather than guessed at.
    """
    return sorted(
        name for name in vars(SQLAlchemyUnitOfWork)
        if not name.startswith("_")
        and isinstance(vars(SQLAlchemyUnitOfWork)[name], property)
        and name not in set(repository_accessors()) | {"session"}
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

    def test_the_implementation_publishes_no_repository_the_port_does_not(
        self
    ):
        """
        The other half of reading the port.

        The list above is the port's, so a repository the implementation
        added on its own would not be in it -- and would then never be
        asked whether it refuses after the context closes. Named here
        rather than guessed at by the shape of the word, which is how the
        old filter missed anything not ending in "s".
        """
        assert implementation_only_properties() == []

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
