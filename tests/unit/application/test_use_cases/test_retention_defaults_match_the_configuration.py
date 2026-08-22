"""
The two roll-ups' defaults, against the settings they come from.

Each use case carries a default retention so that a test can build one
without a configuration object. That is a convenience with a failure mode:
the number is written twice, and the copy in the use case is the one a
suite measures while the service runs on the other. A service whose
history is ninety days and whose tests believe it is thirty is a service
whose sweep is never really tested.

Held against ``BaseConfig`` rather than against a number typed here, for
the same reason: a third copy would need the same test.
"""

from link_shortener.application.use_cases.admin.links.roll_up_visits import (
    RollUpVisitsUseCase,
)
from link_shortener.application.use_cases.admin.security.roll_up_security_events import (
    RollUpSecurityEventsUseCase,
)
from link_shortener.application.utils.chart_spans import PERIODS
from link_shortener.infrastructure.configs.app.base import BaseConfig


class TestEachDefaultIsTheSettingItComesFrom:

    def test_visits_keep_what_the_setting_says(self):
        assert (
            RollUpVisitsUseCase.retention_days
            == BaseConfig.VISIT_RETENTION_DAYS
        )

    def test_security_events_keep_what_their_setting_says(self):
        assert (
            RollUpSecurityEventsUseCase.retention_days
            == BaseConfig.SECURITY_EVENT_RETENTION_DAYS
        )

    def test_the_two_windows_are_not_the_same_by_accident(self):
        """Evidence outlives traffic, and the difference is deliberate."""
        assert (
            BaseConfig.SECURITY_EVENT_RETENTION_DAYS
            > BaseConfig.VISIT_RETENTION_DAYS
        )


class TestTheVisitWindowCoversTheLongestSpanOffered:

    def test_the_sweep_does_not_cut_into_a_span_the_charts_offer(self):
        """
        The bucketed chart reads the raw rows alone -- a folded day keeps
        no device or browser split to fill its breakdowns with. So the
        longest span on offer is answerable only while the sweep leaves
        that many days of raw rows standing. Shorten one without the
        other and the ninety-day view quietly becomes a shorter one, with
        the daily chart below it still reaching all the way back.
        """
        longest = max(span.days for span, _ in PERIODS.values())

        assert BaseConfig.VISIT_RETENTION_DAYS >= longest
