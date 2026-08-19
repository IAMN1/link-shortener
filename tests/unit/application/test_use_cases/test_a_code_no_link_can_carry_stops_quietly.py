"""What happens when a use case is handed a string no link can carry.

Three places caught ``ValueError`` around ``ShortCode(...)``, and
``ShortCode`` raises ``ValidationError``, which descends from ``DomainError``
and not from ``ValueError`` at all. The handlers were unreachable, so the
error left by the front door instead.

Where that costs something is the background task. ``process_link_accessed``
wraps the use case in ``except Exception: self.retry(...)``, so a code the
format rules refuse -- a truncated path, a scanner walking the URL space --
became three retries a minute apart, each one repeating a failure that
cannot succeed on any attempt. The rest is a message: the read paths hand
the caller ``ValidationError``'s own wording rather than the sentence the
dead handler was written to produce.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.application.use_cases.links.update_link_stats import (
    UpdateLinkStatsUseCase,
)
from link_shortener.application.use_cases.stats.get_visit_stats import (
    GetVisitStatsUseCase,
)
from link_shortener.domain.exceptions import ValidationError
from link_shortener.infrastructure.task_queue import tasks


CONTEXT = RequestContext(request_id="test", remote_addr="10.0.0.1")

IMPOSSIBLE = "a"
"""One character: shorter than any code the format allows."""


class TestTheCounterTaskDoesNotRetryWhatCannotSucceed:

    def test_the_use_case_returns_instead_of_raising(self):
        """
        The handler's own intent, restored: log it and stop.
        """
        uow_factory = MagicMock()
        use_case = UpdateLinkStatsUseCase(
            uow_factory=uow_factory, logger=MagicMock()
        )

        use_case.execute(IMPOSSIBLE, CONTEXT)

        # No transaction was opened for a code that can never match a row.
        uow_factory.assert_not_called()

    def test_the_worker_does_not_schedule_a_retry(self):
        """
        The cost of the dead handler, at the level where it was paid.

        ``process_link_accessed`` retries on any exception, so an
        unreachable handler turned one impossible code into three attempts
        sixty seconds apart.
        """
        container = Mock()
        container.get_update_link_stats_use_case.return_value = (
            UpdateLinkStatsUseCase(uow_factory=MagicMock(), logger=MagicMock())
        )

        with patch.object(tasks, "get_container", return_value=container):
            with patch.object(
                tasks.process_link_accessed, "retry"
            ) as retry:
                tasks.process_link_accessed.run(IMPOSSIBLE, CONTEXT.__dict__)

        retry.assert_not_called()


class TestTheReadPathsSayWhatIsWrongWithTheCode:

    @pytest.mark.parametrize("call", [
        lambda uc: uc.execute(CONTEXT, short_code=IMPOSSIBLE),
        lambda uc: uc.daily(CONTEXT, days=7, short_code=IMPOSSIBLE),
    ])
    def test_the_answer_is_a_validation_failure(self, call):
        """
        Both spans, and both used to depend on a handler that never ran.

        The assertion is on the code rather than the sentence: the code is
        what the API turns into a status, and it is the same either way.
        """
        use_case = GetVisitStatsUseCase(
            uow_factory=MagicMock(), logger=MagicMock()
        )

        with pytest.raises(ValidationError) as refused:
            call(use_case)

        assert refused.value.code == "VALIDATION_ERROR"
