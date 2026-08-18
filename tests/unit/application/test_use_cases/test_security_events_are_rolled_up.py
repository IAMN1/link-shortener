"""Folding the days that are over, then sweeping the rows behind them.

The order is the whole of it. Folding writes the day totals; the sweep
deletes the raw rows the totals were computed from. Done the other way
round, the history is deleted and the totals for it are never written --
and the long-range chart loses its past with nothing to recover it from.

The current day is never folded either, for a reason that is easy to miss:
a total written for a day still receiving events is wrong as soon as the
next one lands, and folding twice would then write a smaller number over a
larger one.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.application.use_cases.admin.security.roll_up_security_events import (
    RollUpSecurityEventsUseCase,
)


NOON = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)
MIDNIGHT = NOON.replace(hour=0, minute=0, second=0, microsecond=0)


@pytest.fixture
def uow():
    """A unit of work whose security event repository is watched."""
    unit = Mock()
    unit.__enter__ = Mock(return_value=unit)
    unit.__exit__ = Mock(return_value=False)
    unit.security_events.fold_days_before.return_value = 3
    unit.security_events.delete_before.return_value = 17
    return unit


@pytest.fixture
def uow_factory(uow):
    """A factory handing out that one unit of work."""

    @contextmanager
    def factory(*args, **kwargs):
        yield uow

    return factory


@pytest.fixture
def context():
    """The context a scheduled run carries."""
    return RequestContext(request_id="cli-roll-up-security-events")


class TestFoldingComesFirst:
    """The totals exist before the rows behind them are deleted."""

    def test_both_steps_run(self, uow_factory, uow, context):
        use_case = RollUpSecurityEventsUseCase(
            uow_factory=uow_factory, logger=Mock(), retention_days=90
        )

        folded, swept = use_case.execute(context, now=NOON)

        assert (folded, swept) == (3, 17)

    def test_the_fold_happens_before_the_sweep(
        self, uow_factory, uow, context
    ):
        """Reversed, the rows are gone before anything counted them, and
        the totals for those days are never written at all."""
        order = []
        uow.security_events.fold_days_before.side_effect = (
            lambda **kw: order.append("fold") or 3
        )
        uow.security_events.delete_before.side_effect = (
            lambda *a, **kw: order.append("sweep") or 17
        )
        use_case = RollUpSecurityEventsUseCase(
            uow_factory=uow_factory, logger=Mock(), retention_days=90
        )

        use_case.execute(context, now=NOON)

        assert order == ["fold", "sweep"]

    def test_today_is_not_folded(self, uow_factory, uow, context):
        """Everything before midnight, so the day still receiving events
        is left alone."""
        use_case = RollUpSecurityEventsUseCase(
            uow_factory=uow_factory, logger=Mock(), retention_days=90
        )

        use_case.execute(context, now=NOON)

        assert uow.security_events.fold_days_before.call_args[1]["day"] == MIDNIGHT


class TestTheRetentionWindow:
    """How far back the raw rows are kept."""

    def test_the_cutoff_is_the_window_before_midnight(
        self, uow_factory, uow, context
    ):
        use_case = RollUpSecurityEventsUseCase(
            uow_factory=uow_factory, logger=Mock(), retention_days=365
        )

        use_case.execute(context, now=NOON)

        cutoff = uow.security_events.delete_before.call_args[0][0]
        assert cutoff == MIDNIGHT - timedelta(days=365)

    def test_zero_disables_the_sweep_without_disabling_the_fold(
        self, uow_factory, uow, context
    ):
        """Keeping everything is a choice an operator may make, and the
        charts must go on being correct when they make it."""
        use_case = RollUpSecurityEventsUseCase(
            uow_factory=uow_factory, logger=Mock(), retention_days=0
        )

        folded, swept = use_case.execute(context, now=NOON)

        assert folded == 3
        assert swept == 0
        uow.security_events.delete_before.assert_not_called()
        uow.security_events.fold_days_before.assert_called_once()

    def test_a_year_by_default_unlike_the_visits(self):
        """Evidence outlives traffic: the question asked of a sign-in is
        usually asked long after the fact."""
        use_case = RollUpSecurityEventsUseCase(
            uow_factory=Mock(), logger=Mock()
        )

        assert use_case.retention_days == 365
