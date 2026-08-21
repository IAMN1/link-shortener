"""The unit of work is closed before the authorization service is asked.

``RBACAuthorizationService`` opens a unit of work of its own for an
anonymous caller: the ``guest`` role lives in the database like any other.
Asked from inside an open one, it would open a second -- a second
connection out of the pool, on a deployment of four sync workers, to answer
a question the first transaction could have answered.

Two use cases load the actor and then close the block before asking:
``ReadJournalUseCase`` and ``GetSecurityCountsUseCase``. The property was
stated in a comment in ``rbac_authorization_service`` and held by nothing
-- measured, by moving the call inside the block and running the whole
suite: 3547 passed.

**Why the ceiling is moved here.** Today the nesting cannot happen even if
the call were moved, and not because of anything these use cases do:
``_anonymous_is_allowed`` returns before touching the database for any
permission outside ``ANONYMOUS_PERMISSION_CEILING``, and neither
``audit:view`` nor ``logs:view`` is in it. So the first guard is the
ceiling's contents and the second is the order of the two statements, and a
test that left the first in place would prove nothing about the second: it
would pass with the call in either position. The ceiling is widened for the
length of one test so that the guard being checked is the one this file is
about. What the ceiling admits is a decision that can change -- it has
changed once already -- and the order must not depend on it.
"""

from unittest.mock import Mock

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.journal_reader import Journal
from link_shortener.application.use_cases.journals.read_journal import (
    ReadJournalUseCase,
)
from link_shortener.application.use_cases.security.get_security_counts import (
    GetSecurityCountsUseCase,
)
from link_shortener.domain import DomainError, SystemPermissions
from link_shortener.infrastructure.auth import rbac_authorization_service
from link_shortener.infrastructure.auth.rbac_authorization_service import (
    RBACAuthorizationService,
)


class OneAtATime:
    """A factory that refuses to open a second unit of work.

    ``SQLAlchemyUnitOfWork`` refuses a second *entry into the same
    instance* and says so; nesting builds a fresh instance and is therefore
    allowed by it, quietly. This factory is stricter on purpose -- what is
    being guarded is not an exception the database would raise but a
    connection it would hand out.

    Attributes:
        opened: How many are open right now.
        peak: The most that were ever open at once.
    """

    def __init__(self):
        self.opened = 0
        self.peak = 0
        self.uow = Mock()
        self.uow.users.find_by_id.return_value = None
        self.uow.roles.get_by_name.return_value = None
        self.uow.security_events.buckets_between.return_value = []
        self.uow.__enter__ = Mock(side_effect=self._enter)
        self.uow.__exit__ = Mock(side_effect=self._exit)

    def __call__(self, read_only: bool = False):
        return self.uow

    def _enter(self):
        if self.opened:
            raise AssertionError(
                "a second unit of work was opened inside an open one"
            )
        self.opened += 1
        self.peak = max(self.peak, self.opened)
        return self.uow

    def _exit(self, *_args):
        self.opened -= 1
        return False


@pytest.fixture
def ceiling_admits_the_journals(monkeypatch):
    """Put the journal permissions inside the anonymous ceiling.

    Which makes ``_anonymous_is_allowed`` go to the database for them --
    the branch that opens a unit of work, and the whole reason the two use
    cases close theirs first.
    """
    monkeypatch.setattr(
        rbac_authorization_service,
        "ANONYMOUS_PERMISSION_CEILING",
        frozenset({
            SystemPermissions.LOGS_VIEW.value,
            SystemPermissions.AUDIT_VIEW.value,
        }),
    )


@pytest.mark.usefixtures("ceiling_admits_the_journals")
def test_reading_a_journal_asks_after_its_transaction_is_closed():
    factory = OneAtATime()
    use_case = ReadJournalUseCase(
        reader=Mock(),
        authorization_service=RBACAuthorizationService(
            uow_factory=factory, logger=Mock()
        ),
        uow_factory=factory,
        logger=Mock(),
        audit_logger=Mock(),
    )

    with pytest.raises(DomainError) as refused:
        use_case.execute(Journal.APPLICATION, anonymous_context())

    # Refused because the ``guest`` row is missing from this factory, which
    # is the answer that matters least here. What matters is which
    # exception did not come out: ``AssertionError`` from the factory.
    assert refused.value.code == "UNAUTHENTICATED"
    assert factory.peak == 1, factory.peak


@pytest.mark.usefixtures("ceiling_admits_the_journals")
def test_counting_the_events_asks_after_its_transaction_is_closed():
    factory = OneAtATime()
    use_case = GetSecurityCountsUseCase(
        uow_factory=factory,
        authorization_service=RBACAuthorizationService(
            uow_factory=factory, logger=Mock()
        ),
        logger=Mock(),
    )

    with pytest.raises(DomainError) as refused:
        use_case.execute(anonymous_context())

    assert refused.value.code == "UNAUTHENTICATED"
    assert factory.peak == 1, factory.peak


def anonymous_context() -> RequestContext:
    """A context with nobody signed in.

    Which is the caller that reaches the ``guest`` branch at all: a signed-in
    one is answered from the roles already loaded, and never sends the
    authorization service to the database.

    Returns:
        The context.
    """
    return RequestContext(
        request_id="req-1",
        remote_addr="127.0.0.1",
        request_path="/api/v1/journals/application",
        request_method="GET",
        current_user=None,
    )
