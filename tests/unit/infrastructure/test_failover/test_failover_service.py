"""
Unit tests for ``FailoverService``.

Two directions, and the second is the one that was never checked: falling
down to a standby when the active service throws, and climbing back up when
a higher-priority one recovers. A service that only ever falls is a service
that ends its life on the null implementation.

Time is injected rather than waited for. The upgrade cooldown is five
minutes by default, so the only other way to watch it expire is to sleep for
five minutes -- and a test that sleeps measures the scheduler as much as the
code. ``FakeClock`` starts at a realistic epoch on purpose: the "never
attempted" sentinel inside the service is ``0.0``, which reads as 1970, and
a clock starting near zero would put the service on a code path production
never takes.
"""

import threading
import time

import pytest

from link_shortener.infrastructure.failover.failover_service import (
    FailoverService
)
from link_shortener.infrastructure.failover.minimal_logger import MinimalLogger


# ===========================================================================
# Test doubles
# ===========================================================================

class FakeClock:
    """A clock the test moves by hand."""

    def __init__(self, now: float = 1_700_000_000.0):
        """
        Args:
            now: Starting time in seconds. Realistic by default.
        """
        self.now = now

    def __call__(self) -> float:
        """Return the current time."""
        return self.now

    def advance(self, seconds: float) -> None:
        """
        Move the clock forward.

        Args:
            seconds: How far forward to move.
        """
        self.now += seconds


class RecordingLogger:
    """Collects the failover service's messages instead of printing them."""

    def __init__(self):
        self.warnings = []

    def info(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        self.warnings.append(message)

    def error(self, message: str) -> None:
        pass


class Service:
    """
    A stand-in for one of the interchangeable services.

    Attributes:
        name: Identifies the instance in assertions.
        healthy: What the health checker reports for it.
        broken: Whether ``speak`` raises instead of answering.
        calls: Every ``speak`` call it received, as ``(args, kwargs)``.
    """

    def __init__(self, name: str, healthy: bool = True, broken: bool = False):
        self.name = name
        self.healthy = healthy
        self.broken = broken
        self.calls = []

    def speak(self, *args, **kwargs) -> str:
        """
        Answer with this service's name.

        Raises:
            RuntimeError: If the service is marked broken.
        """
        self.calls.append((args, kwargs))
        if self.broken:
            raise RuntimeError(f"{self.name} is down")
        return f"{self.name} spoke"

    def hush(self) -> None:
        """Succeed and answer nothing, as a real ``log(...)`` call does."""
        self.calls.append((("hush",), {}))
        return None

    def is_healthy(self) -> bool:
        """Report health the way the real Logger port does."""
        return self.healthy


def health_of(service: Service) -> bool:
    """
    Report a fake service's health.

    Args:
        service: The service to inspect.

    Returns:
        Whatever the fake was told to claim.
    """
    return service.healthy


def build(services, clock=None, logger=None, **kwargs):
    """
    Build a service under test with the background thread switched off.

    ``check_interval=None`` unless a test says otherwise: the thread is a
    scheduler, and every test here drives ``_attempt_upgrade`` directly so
    that what is measured is the decision, not when it was taken.

    Args:
        services: List of ``Service`` instances in priority order.
        clock: Injected clock; a fresh ``FakeClock`` if omitted.
        logger: Injected logger; a fresh ``RecordingLogger`` if omitted.
        **kwargs: Passed through to ``FailoverService``.

    Returns:
        Tuple of (service under test, clock, logger).
    """
    clock = clock or FakeClock()
    logger = logger or RecordingLogger()
    kwargs.setdefault("check_interval", None)
    kwargs.setdefault("health_checker", health_of)
    failover = FailoverService(
        services=[(s, s.name) for s in services],
        logger=logger,
        clock=clock,
        **kwargs,
    )
    return failover, clock, logger


# ===========================================================================
# Construction
# ===========================================================================

class TestConstruction:

    def test_an_empty_service_list_is_refused(self):
        with pytest.raises(ValueError, match="At least one service required"):
            FailoverService(services=[], check_interval=None)

    def test_the_first_service_is_the_active_one(self):
        failover, _, _ = build([Service("primary"), Service("standby")])
        assert failover.get_current_service_name() == "primary"

    def test_no_thread_is_started_when_the_interval_is_none(self):
        failover, _, _ = build([Service("primary")], check_interval=None)
        assert failover._thread is None

    def test_a_thread_is_started_when_an_interval_is_given(self):
        failover, _, _ = build([Service("primary")], check_interval=30.0)
        try:
            assert failover._thread is not None
            assert failover._thread.is_alive()
            assert failover._thread.daemon is True
        finally:
            failover.shutdown()

    def test_the_default_logger_writes_to_stderr(self):
        # Not merely "a logger is set": the default is the one that needs no
        # configured logging stack, which is the point of this component.
        failover = FailoverService(
            services=[(Service("primary"), "primary")], check_interval=None
        )
        assert isinstance(failover.logger, MinimalLogger)


# ===========================================================================
# Falling down: execute() and _switch_to_next()
# ===========================================================================

class TestFallingToAStandby:

    def test_a_working_service_answers_and_stays_active(self):
        primary = Service("primary")
        failover, _, _ = build([primary, Service("standby")])

        assert failover.execute("speak") == "primary spoke"
        assert failover.get_current_service_name() == "primary"

    def test_arguments_reach_the_service(self):
        primary = Service("primary")
        failover, _, _ = build([primary])

        # The names the real proxies pass through, not invented ones:
        # FailoverLoggerProxy sends `module=` and `exc_info=`.
        failover.execute("speak", "the message", module="web", exc_info=True)

        assert primary.calls == [
            (("the message",), {"module": "web", "exc_info": True})
        ]

    def test_a_failing_service_hands_over_to_the_next(self):
        primary = Service("primary", broken=True)
        standby = Service("standby")
        failover, _, logger = build([primary, standby])

        assert failover.execute("speak") == "standby spoke"
        assert failover.get_current_service_name() == "standby"
        # Both halves are reported, and nothing else is: what broke, with
        # the reason, and what took over. Substring matching would pass on
        # a message that had lost the exception text.
        assert logger.warnings == [
            "Service primary failed for speak: primary is down. "
            "Attempting switch.",
            "Switched to standby",
        ]

    def test_the_handover_sticks_for_later_calls(self):
        primary = Service("primary", broken=True)
        standby = Service("standby")
        failover, _, _ = build([primary, standby])

        failover.execute("speak")
        primary.calls.clear()
        assert failover.execute("speak") == "standby spoke"

        # The demoted service is not consulted again until an upgrade says
        # so. Retrying it on every call would pay its timeout every time.
        assert primary.calls == []

    def test_it_walks_past_several_broken_services_one_step_at_a_time(self):
        primary = Service("primary", broken=True)
        middle = Service("middle", broken=True)
        last = Service("last")
        failover, _, _ = build([primary, middle, last])

        assert failover.execute("speak") == "last spoke"
        assert failover.get_current_service_name() == "last"
        # Each in turn, and the middle one really was tried. Jumping
        # straight to the end would give the same answer here while
        # skipping a healthy fallback to land on the null implementation.
        assert len(primary.calls) == 1
        assert len(middle.calls) == 1
        assert len(last.calls) == 1

    def test_when_every_service_fails_the_call_returns_none(self):
        primary = Service("primary", broken=True)
        standby = Service("standby", broken=True)
        failover, _, _ = build([primary, standby])

        assert failover.execute("speak") is None
        # Each was tried exactly once. A loop that lost count would either
        # stop early or spin over the list again.
        assert len(primary.calls) == 1
        assert len(standby.calls) == 1
        assert failover.get_current_service_name() == "standby"

    def test_a_method_the_service_does_not_have_counts_as_a_failure(self):
        # getattr raises before any call is made, and the caller should not
        # be able to tell that apart from the service refusing the work.
        failover, _, logger = build([Service("primary"), Service("standby")])

        assert failover.execute("no_such_method") is None
        assert failover.get_current_service_name() == "standby"
        # Both services were tried and the reason names the attribute, so
        # an operator can tell this apart from a service refusing the work.
        assert len(logger.warnings) == 3
        assert "'Service' object has no attribute 'no_such_method'" in (
            logger.warnings[0]
        )

    def test_success_and_total_failure_are_told_apart_by_nothing(self):
        # `execute` answers None when every service failed, and None is also
        # what a method that succeeded and returns nothing answers. The two
        # arrive at the caller identical. It matters: every audit call site
        # discards this return, so an audit trail that has stopped recording
        # looks exactly like one that recorded fine.
        working, _, working_log = build([Service("primary")])
        exhausted, _, _ = build([Service("primary", broken=True)])

        assert working.execute("hush") is None
        assert exhausted.execute("speak") is None

        # The only thing that separates them is a warning nobody reads.
        assert working_log.warnings == []

    def test_a_health_check_is_never_used_to_demote(self):
        # Health decides promotions and nothing else. A service that reports
        # itself unwell keeps the work until one of its calls actually
        # throws -- and StandardLogger reports itself unwell whenever it has
        # no handlers, while its log calls go on returning quietly.
        primary = Service("primary", healthy=False)
        failover, clock, _ = build([primary, Service("standby")])

        clock.advance(301)
        failover._attempt_upgrade()

        assert failover.get_current_service_name() == "primary"
        assert failover.execute("speak") == "primary spoke"

    def test_without_the_background_thread_a_demotion_is_permanent(self):
        # `execute` only ever walks downwards; climbing back is the
        # background thread's job alone. With check_interval=None -- which
        # is how every test here builds it, and a value the constructor
        # accepts -- a service demoted once never gets the work back, however
        # healthy it becomes.
        primary = Service("primary", broken=True)
        failover, clock, _ = build([primary, Service("standby")])

        failover.execute("speak")
        primary.broken = False
        clock.advance(10_000)

        assert failover.execute("speak") == "standby spoke"
        assert failover.get_current_service_name() == "standby"

    def test_switching_from_the_last_service_reports_that_it_cannot(self):
        failover, _, _ = build([Service("primary"), Service("standby")])
        failover._current_index = 1

        assert failover._switch_to_next() is False
        assert failover.get_current_service_name() == "standby"


# ===========================================================================
# Climbing back: _attempt_upgrade()
# ===========================================================================

class TestClimbingBack:

    def test_nothing_happens_while_the_best_service_is_active(self):
        failover, clock, logger = build([Service("primary"), Service("standby")])

        clock.advance(10_000)
        failover._attempt_upgrade()

        assert failover.get_current_service_name() == "primary"
        assert logger.warnings == []

    def test_a_recovered_service_takes_back_the_work(self):
        primary = Service("primary", healthy=False, broken=True)
        standby = Service("standby")
        failover, clock, logger = build([primary, standby])

        failover.execute("speak")
        assert failover.get_current_service_name() == "standby"

        primary.healthy = True
        primary.broken = False
        clock.advance(301)
        failover._attempt_upgrade()

        assert failover.get_current_service_name() == "primary"
        assert logger.warnings[-1] == "Upgrading from standby to primary"

    def test_a_service_that_is_still_sick_does_not_take_it_back(self):
        primary = Service("primary", healthy=False, broken=True)
        failover, clock, _ = build([primary, Service("standby")])
        failover.execute("speak")

        clock.advance(301)
        failover._attempt_upgrade()

        assert failover.get_current_service_name() == "standby"

    def test_the_cooldown_holds_off_an_attempt_made_too_soon(self):
        primary = Service("primary", healthy=False, broken=True)
        failover, clock, _ = build([primary, Service("standby")])
        failover.execute("speak")

        # Spend the first attempt, so the cooldown starts running.
        clock.advance(301)
        failover._attempt_upgrade()
        assert failover.get_current_service_name() == "standby"

        # Healthy again, but the window has not reopened.
        primary.healthy = True
        clock.advance(299)
        failover._attempt_upgrade()
        assert failover.get_current_service_name() == "standby"

        # One second past five minutes, and it goes through.
        clock.advance(2)
        failover._attempt_upgrade()
        assert failover.get_current_service_name() == "primary"

    def test_it_climbs_to_the_best_healthy_service_not_merely_a_better_one(self):
        best = Service("best")
        middle = Service("middle")
        failover, clock, _ = build([best, middle, Service("worst")])
        failover._current_index = 2

        clock.advance(301)
        failover._attempt_upgrade()

        # The list is in priority order, so the first healthy entry wins.
        # Landing on "middle" would be a service that settles for the
        # nearest step up and never reaches the top again.
        assert failover.get_current_service_name() == "best"

    def test_it_skips_a_sick_service_to_reach_a_healthy_one_below_it(self):
        failover, clock, _ = build([
            Service("best", healthy=False),
            Service("middle", healthy=True),
            Service("worst"),
        ])
        failover._current_index = 2

        clock.advance(301)
        failover._attempt_upgrade()

        assert failover.get_current_service_name() == "middle"

    def test_a_health_check_that_raises_is_logged_and_stepped_over(self):
        def explode(service):
            if service.name == "best":
                raise RuntimeError("probe exploded")
            return service.healthy

        failover, clock, logger = build(
            [Service("best"), Service("middle"), Service("worst")],
            health_checker=explode,
        )
        failover._current_index = 2

        clock.advance(301)
        failover._attempt_upgrade()

        assert failover.get_current_service_name() == "middle"
        # The reason the probe failed is the whole value of the message.
        assert logger.warnings == [
            "Health check for best failed: probe exploded",
            "Upgrading from worst to middle",
        ]

    def test_without_a_health_checker_a_broken_service_is_promoted_anyway(self):
        # The constructor's docstring says that with no health checker
        # "only failures during actual calls trigger switching". The code
        # reads `health_checker is None or health_checker(service)`, so with
        # none it upgrades unconditionally -- including back onto a service
        # that has just thrown. Pinned as it behaves, against the docstring,
        # because the two disagree and which one is wrong is the owner's
        # call. Latent here: both managers always pass a checker.
        primary = Service("primary", broken=True, healthy=False)
        failover, clock, _ = build(
            [primary, Service("standby")], health_checker=None
        )
        failover.execute("speak")
        assert failover.get_current_service_name() == "standby"

        clock.advance(301)
        failover._attempt_upgrade()

        assert failover.get_current_service_name() == "primary"
        # And the next call pays for it: the promoted service throws, the
        # work falls back to the standby, and the caller is served a step
        # late. That round trip repeats on every check -- the flap the
        # docstring's reading of this default would have avoided.
        assert failover.execute("speak") == "standby spoke"
        assert failover.get_current_service_name() == "standby"

    def test_a_successful_climb_leaves_no_cooldown_behind_it(self):
        # Pinning what the code does, which is not what the cooldown is for.
        # After an upgrade `_last_upgrade_attempt` is set to 0.0 -- the Unix
        # epoch -- so the next attempt is unconditional however recent the
        # last one was. The comment in the source calls this a reset that
        # allows climbing further, and with three or more services it does.
        # This application never has three: both managers build an order of
        # exactly two, so the only thing left is a cooldown that does not
        # survive the upgrade it followed.
        #
        # The consequence is measured in test_the_cooldown_does_not_survive
        # _a_demotion below. Recorded in DEVELOPER_GUIDE, not changed here:
        # the reset is deliberate in the source and undoing it is the
        # owner's call.
        best = Service("best", healthy=False)
        failover, clock, _ = build([best, Service("middle"), Service("worst")])
        failover._current_index = 2

        clock.advance(301)
        failover._attempt_upgrade()
        assert failover.get_current_service_name() == "middle"
        assert failover._last_upgrade_attempt == 0.0

        # No time passes at all, and the next climb still goes through.
        best.healthy = True
        failover._attempt_upgrade()
        assert failover.get_current_service_name() == "best"

    def test_the_cooldown_does_not_survive_a_demotion(self):
        # The production shape: two services, and a health checker that
        # disagrees with reality -- it reports the primary well while calls
        # to it still throw. That disagreement is the whole reason this
        # component exists, so it is not a contrived premise.
        #
        # Six upgrades inside three minutes, against a five-minute cooldown.
        # Each check hands the work back to a service that fails on the next
        # call, because the 0.0 left behind by the previous upgrade makes
        # every attempt eligible. This is a flap at the check interval, and
        # the cooldown is the thing meant to prevent exactly it.
        primary = Service("primary", broken=True, healthy=True)
        failover, clock, _ = build([primary, Service("standby")])

        upgrades = 0
        for _ in range(6):
            failover.execute("speak")
            assert failover.get_current_service_name() == "standby"
            clock.advance(30)
            failover._attempt_upgrade()
            if failover.get_current_service_name() == "primary":
                upgrades += 1

        assert upgrades == 6
        assert failover._last_upgrade_attempt == 0.0

    def test_a_routine_check_on_a_healthy_primary_spends_the_cooldown(self):
        # The stamp is written before the "already the best" return, so a
        # check that decides to do nothing still books the next five
        # minutes. A primary that breaks a moment after such a check waits
        # out the full cooldown before anything tries to bring it back,
        # rather than the one check interval it should have waited.
        failover, clock, _ = build([Service("primary"), Service("standby")])

        failover._attempt_upgrade()

        assert failover._last_upgrade_attempt == clock.now


# ===========================================================================
# The round trip
# ===========================================================================

class TestTheRoundTrip:

    def test_a_service_falls_to_the_standby_and_climbs_back(self):
        # The whole point of the component in one run: primary breaks under
        # a live call, work continues on the standby, primary recovers, and
        # the next check hands the work back.
        primary = Service("primary")
        standby = Service("standby")
        failover, clock, _ = build([primary, standby])

        assert failover.execute("speak") == "primary spoke"

        primary.broken = True
        primary.healthy = False
        assert failover.execute("speak") == "standby spoke"
        assert failover.get_current_service_name() == "standby"

        primary.broken = False
        primary.healthy = True
        clock.advance(301)
        failover._attempt_upgrade()

        assert failover.get_current_service_name() == "primary"
        assert failover.execute("speak") == "primary spoke"


# ===========================================================================
# The background thread
# ===========================================================================

def wait_until(predicate, timeout: float = 5.0) -> bool:
    """
    Block until a predicate holds, or the deadline passes.

    Returns as soon as the condition is met, so it is not a sleep: it costs
    what the work costs. The deadline exists only so a broken run fails
    instead of hanging.

    Args:
        predicate: Callable returning True when the wait is over.
        timeout: Seconds to keep trying before giving up.

    Returns:
        True if the predicate held before the deadline.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.001)
    return False


class TestTheBackgroundThread:

    def test_the_thread_climbs_back_on_its_own(self):
        # The seam every other test in this file steps around. Elsewhere
        # `check_interval` is None and `_attempt_upgrade` is called by hand,
        # so the thread and the decision it exists to make are never
        # exercised together -- and `_attempt_upgrade` has no caller in the
        # application other than this thread.
        #
        # Nothing is stubbed here. The promotion is required to happen on a
        # later tick than the first, so a thread that runs once and dies,
        # or a loop rewritten into a single `if`, fails rather than passes.
        primary = Service("primary", broken=True, healthy=False)
        probes = []

        def probe(service):
            probes.append(service.name)
            return service.healthy

        clock = FakeClock()
        failover, _, _ = build(
            [primary, Service("standby")],
            clock=clock,
            check_interval=0.01,
            health_checker=probe,
        )
        try:
            assert failover.execute("speak") == "standby spoke"

            # A first round of checks, with the primary still unwell.
            assert wait_until(lambda: len(probes) >= 1), "no check ever ran"
            assert failover.get_current_service_name() == "standby"

            # Now let it recover, and open the cooldown window.
            primary.broken = False
            primary.healthy = True
            clock.advance(301)

            assert wait_until(
                lambda: failover.get_current_service_name() == "primary"
            ), "the thread never climbed back"
            assert failover.execute("speak") == "primary spoke"
        finally:
            failover.shutdown()

    def test_shutdown_stops_the_thread_before_it_returns(self):
        # `shutdown()` joins the thread itself, so a caller that has been
        # told the service is down may rely on it. A test that does its own
        # join afterwards would measure its own patience instead.
        failover, _, _ = build([Service("primary")], check_interval=0.01)
        assert failover._thread.is_alive()

        failover.shutdown()

        assert failover._thread.is_alive() is False

    def test_shutdown_is_safe_when_no_thread_was_started(self):
        failover, _, _ = build([Service("primary")], check_interval=None)
        failover.shutdown()
        assert failover._stop_event.is_set()

    def test_shutdown_twice_is_not_an_error(self):
        # Both managers forward shutdown from the DI lifecycle, which can
        # run more than once.
        failover, _, _ = build([Service("primary")], check_interval=0.01)
        failover.shutdown()
        failover.shutdown()
        assert failover._thread.is_alive() is False
