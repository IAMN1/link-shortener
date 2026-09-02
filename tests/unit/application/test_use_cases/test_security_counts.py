"""Reading the counted events, and deciding who may.

The permission is the interesting half. These figures are the audit
journal counted, so they answer to `audit:view` -- and `admin:all`
deliberately does not carry it, which means an administrator asking for
them is refused. A use case that asked for `stats:view_basic` instead, or
for nothing at all, would hand the record kept about administrators to
every administrator, and every test about the numbers would still pass.
"""

from contextlib import contextmanager
from datetime import datetime, time, timedelta, timezone
from unittest.mock import Mock

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.current_user_info import CurrentUserInfo
from link_shortener.application.use_cases.security.get_security_counts import (
    DEFAULT_PERIOD, PERIODS, GetSecurityCountsUseCase,
)
from link_shortener.domain import DomainError, Email, PasswordHash, SystemPermissions
from link_shortener.domain.entities.permission import Permission
from link_shortener.domain.entities.role import Role
from link_shortener.domain.entities.user import User
from link_shortener.infrastructure.auth.rbac_authorization_service import (
    RBACAuthorizationService,
)


NOON = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)


def user_holding(*names: str) -> User:
    """
    A user carrying exactly the named permissions, through one role.

    Args:
        names: Permission names the user's role grants.

    Returns:
        The user entity.
    """
    permissions = []
    for name in names:
        resource, action = name.split(":", 1)
        permissions.append(
            Permission(id=f"p-{name}", name=name, resource=resource, action=action)
        )
    role = Role(id="r-1", name="under-test", permissions=tuple(permissions))
    return User.create(
        email=Email("reader@example.com"),
        password_hash=PasswordHash("not-checked-here"),
        roles=[role],
    )


@pytest.fixture
def uow():
    """A unit of work whose security event repository answers with figures."""
    unit = Mock()
    unit.__enter__ = Mock(return_value=unit)
    unit.__exit__ = Mock(return_value=False)
    unit.users.find_by_id.return_value = None
    unit.security_events.counts_between.return_value = [("LOGIN_FAILED", 11)]
    unit.security_events.buckets_between.return_value = [
        ("LOGIN_FAILED", [0, 11, 0])
    ]
    return unit


@pytest.fixture
def uow_factory(uow):
    """A factory handing out that one unit of work."""

    @contextmanager
    def factory(*args, **kwargs):
        yield uow

    return factory


@pytest.fixture
def use_case(uow_factory):
    """The use case over the real authorization service.

    Real rather than mocked, because half of what is checked here is
    *which* permission is asked for, and a mock that answers True to
    anything would pass whatever was asked.
    """
    return GetSecurityCountsUseCase(
        uow_factory=uow_factory,
        authorization_service=RBACAuthorizationService(
            uow_factory=None, logger=Mock()
        ),
        logger=Mock(),
    )


def signed_in_as(user, uow) -> RequestContext:
    """
    Put a user behind both the context and the database read.

    Args:
        user: The domain user, or ``None`` for an anonymous request.
        uow: The unit of work whose repository answers.

    Returns:
        The matching request context.
    """
    uow.users.find_by_id.return_value = user
    if user is None:
        return RequestContext(request_id="req-1")
    return RequestContext(
        request_id="req-1",
        current_user=CurrentUserInfo(
            id=user.id, email=str(user.email), roles=["under-test"],
            is_active=True,
        ),
    )


class TestTheFiguresAnswerToTheAuditPermission:
    """The same door the journal itself opens under."""

    def test_audit_view_opens_them(self, use_case, uow):
        context = signed_in_as(
            user_holding(SystemPermissions.AUDIT_VIEW.value), uow
        )

        counts = use_case.execute(context, now=NOON)

        assert counts.totals == [("LOGIN_FAILED", 11)]

    def test_an_administrator_is_refused(self, use_case, uow):
        """`admin:all` does not carry `audit:view`, and these numbers are
        the record kept about administrators."""
        context = signed_in_as(
            user_holding(SystemPermissions.ADMIN_ALL.value), uow
        )

        with pytest.raises(DomainError) as refused:
            use_case.execute(context, now=NOON)

        assert refused.value.code == "FORBIDDEN"

    def test_the_statistics_permission_does_not_open_them(self, use_case, uow):
        """They are not statistics about traffic; they are an audit trail
        with the details taken out."""
        context = signed_in_as(
            user_holding(SystemPermissions.STATS_VIEW_BASIC.value), uow
        )

        with pytest.raises(DomainError) as refused:
            use_case.execute(context, now=NOON)

        assert refused.value.code == "FORBIDDEN"

    def test_an_anonymous_caller_is_told_to_log_in(self, use_case, uow):
        """A different refusal from the one above, because "log in" is the
        wrong advice for somebody already logged in as the wrong person."""
        context = signed_in_as(None, uow)

        with pytest.raises(DomainError) as refused:
            use_case.execute(context, now=NOON)

        assert refused.value.code == "UNAUTHENTICATED"

    def test_the_figures_are_not_read_before_the_permission_is_checked(
        self, use_case, uow
    ):
        context = signed_in_as(
            user_holding(SystemPermissions.ADMIN_ALL.value), uow
        )

        with pytest.raises(DomainError):
            use_case.execute(context, now=NOON)

        uow.security_events.counts_between.assert_not_called()


class TestTheSpansOnOffer:
    """Fixed, because a free span is a free bucket count."""

    @pytest.mark.parametrize("period", sorted(PERIODS))
    def test_each_one_asks_for_its_own_width(self, use_case, uow, period):
        context = signed_in_as(
            user_holding(SystemPermissions.AUDIT_VIEW.value), uow
        )

        counts = use_case.execute(context, period=period, now=NOON)

        span, buckets = PERIODS[period]
        assert counts.buckets == buckets
        # Every bucket is the same width, and it is the width the period
        # promises: the span divided by the number of intervals.
        assert (counts.until - counts.since) / buckets == span / buckets

    @pytest.mark.parametrize("period", ["30d", "90d"])
    def test_a_span_drawn_in_days_is_drawn_on_the_days_themselves(
        self, use_case, uow, period
    ):
        """The buckets are dates, so they start and end at midnight.

        Without that the folded day totals cannot be read at all -- a
        fold is a total between midnights, and it cannot be laid on a
        bucket running from whatever time of day the page was opened --
        and the axis under the chart labels these buckets with dates,
        which is only honest if a bucket is one. The last bucket is
        today, still filling up, so the end is the midnight after now.
        """
        context = signed_in_as(
            user_holding(SystemPermissions.AUDIT_VIEW.value), uow
        )

        counts = use_case.execute(context, period=period, now=NOON)

        midnight = NOON.replace(hour=0, minute=0, second=0, microsecond=0)
        assert counts.until == midnight + timedelta(days=1)
        assert counts.since == counts.until - timedelta(days=counts.buckets)

    @pytest.mark.parametrize("period", ["24h", "7d"])
    def test_a_span_drawn_finer_than_a_day_ends_now(
        self, use_case, uow, period
    ):
        """An hour of a day-long span is the hour that just passed, and
        rounding it to the clock would answer a different question."""
        context = signed_in_as(
            user_holding(SystemPermissions.AUDIT_VIEW.value), uow
        )

        counts = use_case.execute(context, period=period, now=NOON)

        span, _ = PERIODS[period]
        assert counts.until == NOON
        assert counts.since == NOON - span

    def test_anything_else_is_refused(self, use_case, uow):
        context = signed_in_as(
            user_holding(SystemPermissions.AUDIT_VIEW.value), uow
        )

        with pytest.raises(DomainError) as refused:
            use_case.execute(context, period="all-of-it", now=NOON)

        assert refused.value.code == "VALIDATION_ERROR"

    def test_the_default_is_a_week(self, use_case, uow):
        """The name of this test is the claim, so the literal is the check.

        Written as ``counts.period == DEFAULT_PERIOD`` the same constant
        supplied both sides: changing the default to ``"24h"`` left it
        green under a name promising a week, and no literal ``"7d"``
        appeared anywhere in the suite.
        """
        context = signed_in_as(
            user_holding(SystemPermissions.AUDIT_VIEW.value), uow
        )

        counts = use_case.execute(context, now=NOON)

        assert DEFAULT_PERIOD == "7d"
        assert counts.period == "7d"

    def test_the_spans_are_the_visit_charts_own_spans(self):
        """Two charts about one service must be about the same days.

        Not "equal to" -- the same object. Two tables kept equal by
        comparison were equal in the two things a comparison of them could
        see, the names and the widths, and differed in the one it could
        not: where a span starts. Measured at 14:37 UTC, the thirty-day
        answers covered windows 9 h 23 min apart.
        """
        from link_shortener.application.use_cases.stats.get_visit_stats import (
            PERIODS as VISIT_PERIODS,
        )
        from link_shortener.application.utils import chart_spans

        assert PERIODS is chart_spans.PERIODS
        assert VISIT_PERIODS is chart_spans.PERIODS

    @pytest.mark.parametrize("period", ["30d", "90d"])
    def test_a_span_drawn_in_days_starts_on_one(self, use_case, uow, period):
        """
        The alignment, asked of this use case rather than of the helper.

        Both are drawn in whole-day buckets, and both are read off an axis
        labelled with dates -- which is only true if a bucket is a date.

        Args:
            period: The two spans whose buckets are one day wide.
        """
        context = signed_in_as(
            user_holding(SystemPermissions.AUDIT_VIEW.value), uow
        )

        counts = use_case.execute(context, period=period, now=NOON)

        assert counts.since.time() == time(0, 0)
        assert counts.until.time() == time(0, 0)


class TestWhatComesBack:
    """Totals and series, because two questions are asked of one span."""

    def test_both_shapes_are_returned(self, use_case, uow):
        context = signed_in_as(
            user_holding(SystemPermissions.AUDIT_VIEW.value), uow
        )

        counts = use_case.execute(context, now=NOON)

        assert counts.totals == [("LOGIN_FAILED", 11)]
        assert counts.series == [("LOGIN_FAILED", [0, 11, 0])]

    def test_a_quiet_span_comes_back_empty_rather_than_missing(
        self, use_case, uow
    ):
        """Nothing happened is an answer, and a page that cannot tell it
        from "no data" says "Loading..." forever."""
        uow.security_events.counts_between.return_value = []
        uow.security_events.buckets_between.return_value = []
        context = signed_in_as(
            user_holding(SystemPermissions.AUDIT_VIEW.value), uow
        )

        counts = use_case.execute(context, now=NOON)

        assert counts.totals == []
        assert counts.series == []
        assert counts.buckets == PERIODS[DEFAULT_PERIOD][1]
