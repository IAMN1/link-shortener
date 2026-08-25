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
    ALL_SERVICES_FAILED,
    FailoverService,
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


class RoundsThatExplode(FailoverService):
    """A service whose first few background rounds throw.

    The loop guards ``_run_check`` so that one bad round costs that round
    and not the thread. Reaching that guard needs a round that raises, and
    the logger can no longer be it: every line goes through ``_say``,
    which absorbs. Subclassed rather than patched after construction --
    ``__init__`` starts the thread, so an attribute set afterwards arrives
    a round or two late.
    """

    def __init__(self, *args, explosions: int, **kwargs):
        """
        Args:
            explosions: How many rounds to lose before working normally.
            *args, **kwargs: Passed through to ``FailoverService``.
        """
        self.explosions = explosions
        super().__init__(*args, **kwargs)

    def _run_check(self) -> None:
        """Throw for the first ``explosions`` rounds, then check for real."""
        if self.explosions > 0:
            self.explosions -= 1
            raise ValueError("I/O operation on closed file")
        super()._run_check()


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
    scheduler, and a test that wants a decision calls for it directly --
    ``_attempt_upgrade``, ``_attempt_demotion`` or the round around them --
    so that what is measured is the decision, not when it was taken. The
    tests in ``TestTheBackgroundThread`` are the ones that want the timing,
    and they pass an interval.

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

    def test_a_service_that_has_lost_nothing_says_so(self):
        # Zero is the reading an operator acts on: a counter that starts at
        # one, or a property that adds one to what it counted, is a service
        # reporting losses it never had. Both counters are read here rather
        # than where they are incremented, because this is the only place
        # their value is known without running anything.
        failover, _, _ = build([Service("primary"), Service("standby")])

        assert failover.failed_checks == 0
        assert failover.dropped_calls == 0

    def test_a_thread_is_started_when_an_interval_is_given(self):
        failover, _, _ = build([Service("primary")], check_interval=30.0)
        try:
            assert failover._thread is not None
            assert failover._thread.is_alive()
            assert failover._thread.daemon is True
        finally:
            failover.shutdown()

    def test_the_default_logger_is_the_one_that_needs_no_setup(self):
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

    def test_the_handover_names_the_service_it_moved_to(self):
        # On two services a message built from either end of the list reads
        # the same, which is why the climb and the demotion are both named
        # on three (`test_the_climb_names_the_service_it_left`,
        # `test_the_demotion_names_both_ends_of_the_move`). This third
        # message had no such check: measured, building it from
        # `self._services[-1][1]` -- the bottom of the list rather than the
        # next step down -- left the whole file green, and an operator
        # reading the log was told the work had gone to the last standby
        # while it had gone to the first.
        failover, _, logger = build([
            Service("primary", broken=True),
            Service("middle"),
            Service("worst"),
        ])

        assert failover.execute("speak") == "middle spoke"

        assert logger.warnings[-1] == "Switched to middle"

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

    def test_when_every_service_fails_the_call_says_so(self):
        primary = Service("primary", broken=True)
        standby = Service("standby", broken=True)
        failover, _, _ = build([primary, standby])

        assert failover.execute("speak") is ALL_SERVICES_FAILED
        # Each was tried exactly once. A loop that lost count would either
        # stop early or spin over the list again.
        assert len(primary.calls) == 1
        assert len(standby.calls) == 1
        assert failover.get_current_service_name() == "standby"

    def test_a_method_the_service_does_not_have_counts_as_a_failure(self):
        # getattr raises before any call is made, and the caller should not
        # be able to tell that apart from the service refusing the work.
        failover, _, logger = build([Service("primary"), Service("standby")])

        assert failover.execute("no_such_method") is ALL_SERVICES_FAILED
        assert failover.get_current_service_name() == "standby"
        # Both services were tried and the reason names the attribute, so
        # an operator can tell this apart from a service refusing the work.
        # Four lines: two refusals, one switch, and the call being dropped.
        assert len(logger.warnings) == 4
        assert "'Service' object has no attribute 'no_such_method'" in (
            logger.warnings[0]
        )

    def test_success_and_total_failure_are_told_apart(self):
        # A method that succeeds and returns nothing answers None, so None
        # cannot also mean "nothing handled this". It mattered: every audit
        # call site discards the return, and an audit trail that had stopped
        # recording looked exactly like one that recorded fine.
        working, _, working_log = build([Service("primary")])
        exhausted, _, _ = build([Service("primary", broken=True)])

        assert working.execute("hush") is None
        assert exhausted.execute("speak") is ALL_SERVICES_FAILED

        # Truthy, as PEP 661 specifies for sentinels: a falsy one puts
        # success and exhaustion back under one `if not result`, which is
        # the confusion this object exists to end. `is` is the only test
        # that answers, so nothing may make `==` answer instead.
        assert bool(ALL_SERVICES_FAILED) is True
        assert ALL_SERVICES_FAILED != None  # noqa: E711 - the point is ==
        assert repr(ALL_SERVICES_FAILED) == "ALL_SERVICES_FAILED"

        # A success is still a success, and says nothing.
        assert working_log.warnings == []
        assert working.dropped_calls == 0

    def test_a_dropped_call_is_counted_and_said_out_loud(self):
        # The return value is only useful to a caller that looks, and none
        # of the audit call sites do. The count is what an operator can be
        # shown, and the line is what lands in the log the moment it
        # happens -- distinct from the "failing over" lines, which are this
        # class working normally rather than giving up.
        exhausted, _, log = build([Service("primary", broken=True)])

        exhausted.execute("speak")
        exhausted.execute("speak")

        # A call that failed over and then succeeded is not a dropped call.
        # Counting in the `except` branch instead gives the same two here
        # on a one-service chain, and starts counting ordinary hand-overs
        # as lost records the moment there is a standby that works.
        recovered, _, _ = build([Service("primary", broken=True), Service("standby")])
        assert recovered.execute("speak") == "standby spoke"
        assert recovered.dropped_calls == 0

        assert exhausted.dropped_calls == 2
        dropped = [line for line in log.warnings if "was dropped" in line]
        assert len(dropped) == 2
        assert "speak" in dropped[0]
        # The running total, and the first line already says one rather
        # than zero: counting after the line is written makes the first
        # drop report none, which is what an operator alerts on.
        assert "(1 so far)" in dropped[0]
        assert "(2 so far)" in dropped[1]

    def test_a_service_failing_in_an_unexpected_way_is_still_a_failure(self):
        # `execute` promises it does not raise, because everything that
        # goes through it is logging: an exception here takes the request
        # down with the line it was trying to write. The failures the
        # doubles above raise are RuntimeError, so narrowing the except to
        # the types this file happens to use would keep every other test
        # green while an OSError from a full disk escaped into the caller.
        class Unusual:
            def speak(self):
                raise OSError(28, "No space left on device")

            def is_healthy(self):
                return True

        failover = FailoverService(
            services=[(Unusual(), "unusual")],
            check_interval=None,
            logger=RecordingLogger(),
        )

        assert failover.execute("speak") is ALL_SERVICES_FAILED
        assert failover.dropped_calls == 1

    def test_threads_failing_at_once_do_not_skip_a_healthy_standby(self):
        # Four threads fail on the primary at the same moment. Each
        # switches only from the index its own call was made on, so the
        # first one moves the work and the rest retry on what it moved to;
        # switching unconditionally lands the work two places down, past a
        # standby that was working: on three services, without the guard,
        # the healthy standby is skipped in twenty runs out of twenty.
        class SlowlyBroken(Service):
            """Fails, but not before every thread has arrived to fail."""

            def speak(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                # Wide enough that all four threads are inside `execute`
                # before the first one gets to switch, which is the window
                # the guard has to work in. The lock is not what closes it:
                # it covers the state and not the call, so all four do
                # reach this service and each pays for its own failure --
                # asserted below, because that is the price of the narrow
                # lock and it should not change unnoticed.
                time.sleep(0.02)
                raise RuntimeError("primary is down")

        primary = SlowlyBroken("primary")
        standby = Service("standby")
        last = Service("last")
        failover, _, _ = build([primary, standby, last])

        workers = 4
        barrier = threading.Barrier(workers)
        results = []

        def worker():
            barrier.wait()
            results.append(failover.execute("speak"))

        threads = [threading.Thread(target=worker) for _ in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # Everyone was served by the first service that works, and the
        # third was never reached.
        assert failover.get_current_service_name() == "standby"
        assert set(results) == {"standby spoke"}
        assert last.calls == []
        # Each of the four reached the broken service once: the narrow lock
        # lets them all arrive, and the guard is what stops them each
        # switching. Widening the lock again makes this a one. The margin
        # here is the 0.02 s sleep above rather than anything logical --
        # 40 runs, half of them at a load average above 11, and it has not
        # moved, but it is the one assertion in this file that rests on a
        # duration.
        assert len(primary.calls) == workers

    def test_a_call_tries_each_service_once_and_no_more(self):
        # A thread whose failure was overtaken by someone else's switch
        # retries where the list now points rather than moving it again, and
        # something has to stop it retrying. Here every call is overtaken --
        # the service moves the index itself -- so nothing but the count of
        # attempts ends the walk: two services, two calls, then the call is
        # dropped.
        overtakes = [3]

        class Overtaken(Service):
            """Fails, and has someone else move the index first."""

            def speak(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                if overtakes[0] > 0:
                    overtakes[0] -= 1
                    with failover._lock:
                        failover._current_index = 0
                raise RuntimeError(f"{self.name} is down")

        primary = Overtaken("primary")
        standby = Overtaken("standby")
        failover, _, _ = build([primary, standby])

        assert failover.execute("speak") is ALL_SERVICES_FAILED
        assert len(primary.calls) + len(standby.calls) == 2


    def test_an_upgrade_check_on_its_own_never_demotes(self):
        # The two directions are separate methods, and the one that climbs
        # does not descend: given a sick service already at the top it
        # leaves the work there. What takes it down is _attempt_demotion,
        # which TestHandingTheWorkDown holds.
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
        # With no checker an upgrade asks nothing: `health_checker is None
        # or health_checker(service)` takes the first branch, and the work
        # goes back to the top of the list once the cooldown has run out --
        # including onto a service that has just thrown. Recovery without a
        # probe cannot be anything else, and the constructor's docstring
        # now says so. Latent here: both managers always pass a checker.
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
        # late. The cooldown holds the repeat down to once per five minutes;
        # the docstring's reading of this default would have avoided it
        # altogether.
        assert failover.execute("speak") == "standby spoke"
        assert failover.get_current_service_name() == "standby"

    def test_a_successful_climb_costs_the_cooldown_like_any_other(self):
        # An upgrade does not give the cooldown back. It used to: the stamp
        # was cleared to 0.0 -- the Unix epoch -- so the attempt after a
        # successful one was unconditional however recent it was.
        primary = Service("primary", healthy=False, broken=True)
        failover, clock, _ = build([primary, Service("standby")])
        failover.execute("speak")
        assert failover.get_current_service_name() == "standby"

        primary.healthy = True
        primary.broken = False
        clock.advance(301)
        failover._attempt_upgrade()

        assert failover.get_current_service_name() == "primary"
        assert failover._last_upgrade_attempt == clock.now

        # The primary breaks again a minute later. The work goes back down,
        # and it stays down until the cooldown that the climb spent runs
        # out -- not until the next check.
        primary.broken = True
        clock.advance(60)
        assert failover.execute("speak") == "standby spoke"
        primary.broken = False
        failover._attempt_upgrade()
        assert failover.get_current_service_name() == "standby"

        clock.advance(241)
        failover._attempt_upgrade()
        assert failover.get_current_service_name() == "primary"

    def test_a_flapping_primary_is_taken_back_once_per_cooldown(self):
        # The production shape: two services, and a health checker that
        # disagrees with reality -- it reports the primary well while calls
        # to it still throw. That disagreement is the whole reason this
        # component exists, so it is not a contrived premise.
        #
        # Six checks inside three minutes, against a five-minute cooldown.
        # Each upgrade hands the work back to a service that fails on the
        # next call, so what the cooldown buys is how often that round trip
        # is paid for. With the stamp cleared after every climb it was paid
        # six times out of six; the cooldown holds it to one.
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

        assert upgrades == 1


    def test_a_routine_check_on_a_healthy_primary_costs_no_cooldown(self):
        # Nearly every check finds the work already on the best service and
        # has nothing to do. Stamping the cooldown before that exit booked
        # the next five minutes for an attempt that never happened, so a
        # primary breaking a moment later waited out the whole cooldown
        # instead of the one check interval it should have.
        failover, clock, _ = build([Service("primary"), Service("standby")])

        failover._attempt_upgrade()

        assert failover._last_upgrade_attempt == 0.0


    def test_the_climb_names_the_service_it_left(self):
        # On two services -- the shape both managers build -- the service
        # being left is the last in the list and also the one just after
        # the target, so a line built from either reads correctly and the
        # mistake never shows. Four services with the work in the middle
        # separate all three: the one left is neither last nor adjacent to
        # where it lands.
        failover, clock, logger = build([
            Service("best"),
            Service("second"),
            Service("third"),
            Service("worst"),
        ])
        failover._current_index = 2
        clock.advance(301)

        failover._attempt_upgrade()

        assert failover.get_current_service_name() == "best"
        assert logger.warnings[-1] == "Upgrading from third to best"


# ===========================================================================
# Handing the work down: _attempt_demotion()
# ===========================================================================

class TestHandingTheWorkDown:

    def test_a_service_that_reports_itself_unwell_hands_the_work_down(self):
        # The failure this component exists for does not raise: a standard
        # logger that has lost its handlers answers False and goes on
        # accepting calls. Nothing else takes the work off it.
        primary = Service("primary", healthy=False)
        failover, _, logger = build([primary, Service("standby")])

        failover._attempt_demotion()

        assert failover.get_current_service_name() == "standby"
        assert logger.warnings == [
            "Demoting from primary to standby: primary reports itself "
            "unhealthy"
        ]

    def test_a_service_that_answers_for_itself_keeps_the_work(self):
        failover, _, logger = build([Service("primary"), Service("standby")])

        failover._attempt_demotion()

        assert failover.get_current_service_name() == "primary"
        assert logger.warnings == []

    def test_the_work_stays_where_it_is_when_nothing_below_answers(self):
        # Two unwell services are not a reason to shuffle between them, and
        # the state is said out loud because it is the state in which
        # records are being lost. Only about what is below, though: the
        # round is not over, and the climb that follows may still move the
        # work up.
        failover, _, logger = build([
            Service("primary", healthy=False),
            Service("standby", healthy=False),
        ])

        assert failover._attempt_demotion() is False

        assert failover.get_current_service_name() == "primary"
        assert logger.warnings == [
            "primary reports itself unhealthy and nothing below it answers"
        ]

    def test_it_reports_whether_the_work_moved(self):
        # `_run_check` reads this to decide whether to climb afterwards, so
        # the answer is part of the contract rather than a convenience.
        moved, _, _ = build([Service("a", healthy=False), Service("b")])
        stayed, _, _ = build([Service("a"), Service("b")])

        assert moved._attempt_demotion() is True
        assert stayed._attempt_demotion() is False

    def test_it_passes_over_a_standby_that_is_unwell_too(self):
        failover, _, _ = build([
            Service("best", healthy=False),
            Service("middle", healthy=False),
            Service("worst", healthy=True),
        ])

        failover._attempt_demotion()

        assert failover.get_current_service_name() == "worst"

    def test_without_a_health_checker_nothing_is_handed_down(self):
        # No checker, nothing to ask, and silence is not an answer.
        primary = Service("primary", healthy=False)
        failover, _, logger = build(
            [primary, Service("standby")], health_checker=None
        )

        failover._attempt_demotion()

        assert failover.get_current_service_name() == "primary"
        assert logger.warnings == []

    def test_a_probe_that_raises_on_the_active_service_moves_nothing(self):
        # An unanswered probe answers nothing. Moving the work on it would
        # let a broken checker empty the top of the list.
        def explode(service):
            raise RuntimeError("probe exploded")

        failover, _, logger = build(
            [Service("primary"), Service("standby")], health_checker=explode
        )

        # The answer matters as much as the index: `_run_check` reads it to
        # decide whether to climb, so a raise reported as "the work moved"
        # costs the climb -- see the round-level test below.
        assert failover._attempt_demotion() is False

        assert failover.get_current_service_name() == "primary"
        assert logger.warnings == ["Health check for primary failed: probe exploded"]

    def test_a_probe_that_raises_on_a_candidate_is_stepped_over(self):
        def explode(service):
            if service.name == "middle":
                raise RuntimeError("probe exploded")
            return service.healthy

        failover, _, logger = build(
            [
                Service("best", healthy=False),
                Service("middle"),
                Service("worst"),
            ],
            health_checker=explode,
        )

        failover._attempt_demotion()

        assert failover.get_current_service_name() == "worst"
        assert logger.warnings == [
            "Health check for middle failed: probe exploded",
            "Demoting from best to worst: best reports itself unhealthy",
        ]

    def test_it_never_hands_the_work_up_the_list(self):
        # Down is down. A demotion that scanned from the top of the list
        # instead of from below the active service would take the work back
        # up without asking the cooldown -- the flap the cooldown exists to
        # stop, arriving through the other door.
        best = Service("best", healthy=True, broken=True)
        worst = Service("worst", healthy=False)
        failover, _, _ = build([best, worst])
        failover._switch_to_next()

        moved = failover._attempt_demotion()

        assert moved is False
        assert failover.get_current_service_name() == "worst"

    def test_a_demotion_lands_on_the_next_service_that_answers(self):
        # The nearest one below, not the last one that happens to answer.
        # Climbing is held to the same rule by
        # test_it_climbs_to_the_best_healthy_service_not_merely_a_better_one;
        # with two healthy candidates below, nothing held this direction.
        failover, _, _ = build([
            Service("best", healthy=False),
            Service("middle", healthy=True),
            Service("worst", healthy=True),
        ])

        assert failover._attempt_demotion() is True

        assert failover.get_current_service_name() == "middle"


    def test_a_demotion_does_not_wait_out_the_upgrade_cooldown(self):
        # The cooldown holds off attempts to climb, so that a service that
        # keeps breaking is not handed the work every half minute. Taking
        # the work off a service that says it cannot do it is the opposite
        # errand and waits for nothing.
        primary = Service("primary", healthy=False, broken=True)
        failover, clock, _ = build([primary, Service("standby")])
        failover.execute("speak")
        clock.advance(301)
        primary.healthy = True
        primary.broken = False
        failover._attempt_upgrade()
        assert failover.get_current_service_name() == "primary"

        # The cooldown has just been spent; the demotion goes through
        # anyway.
        primary.healthy = False
        failover._attempt_demotion()

        assert failover.get_current_service_name() == "standby"

    def test_the_demotion_names_both_ends_of_the_move(self):
        # Same blind spot as the climb, at both ends: with two services the
        # one being left is the first in the list and the one taken is the
        # last, so a line built from either end reads correctly. Four
        # services, handing down from the second to the third, separate
        # them -- neither end of the list is the answer.
        failover, _, logger = build([
            Service("best"),
            Service("second", healthy=False),
            Service("third"),
            Service("worst"),
        ])
        failover._current_index = 1

        failover._attempt_demotion()

        assert failover.get_current_service_name() == "third"
        assert logger.warnings[-1] == (
            "Demoting from second to third: second reports itself unhealthy"
        )

    def test_a_logger_that_throws_on_the_announcement_keeps_the_demotion(self):
        # The same once-unprotected announcement as in the climb, and the
        # same loss: the work stayed on a service that had just said it
        # could not do the work. Held now by `_say` absorbing the throw.
        class ThrowsOnDemotion(RecordingLogger):
            def warning(self, message: str) -> None:
                super().warning(message)
                if message.startswith("Demoting"):
                    raise ValueError("I/O operation on closed file")

        logger = ThrowsOnDemotion()
        failover, _, _ = build(
            [Service("primary", healthy=False), Service("standby")],
            logger=logger,
        )

        failover._attempt_demotion()

        assert failover.get_current_service_name() == "standby"
        assert failover.lost_log_lines == 1


# ===========================================================================
# One round of the background check: _run_check()
# ===========================================================================

class TestARoundOfChecking:

    def test_a_round_that_hands_the_work_down_does_not_climb_after_it(self):
        # The climb would ask the service just demoted whether it is well,
        # in the same round, with the same checker -- and book the five
        # minute cooldown on an answer it already has. With the climb in
        # place, a primary handed down by the probe and healthy again a
        # moment later waits 300 s for the work, against 30 s when
        # the same demotion came from a call that threw.
        primary = Service("primary", healthy=False)
        failover, clock, _ = build([primary, Service("standby")])

        failover._run_check()
        assert failover.get_current_service_name() == "standby"
        assert failover._last_upgrade_attempt == 0.0

        primary.healthy = True
        clock.advance(30)
        failover._run_check()

        assert failover.get_current_service_name() == "primary"

    def test_the_work_goes_down_before_it_goes_up_from_the_middle(self):
        # The test above holds the same rule with the work on the best
        # service, where the climb returns at once and spends nothing --
        # so it stays true even with the two halves of the round swapped.
        # From the middle of the list they are told apart: taking the
        # rounds in the other order climbs away from a service that has
        # just said it is unwell, and books the cooldown doing it.
        best = Service("best")
        middle = Service("middle", healthy=False)
        failover, _, _ = build([best, middle, Service("worst")])
        failover._current_index = 1

        failover._run_check()

        assert failover.get_current_service_name() == "worst"
        assert failover._last_upgrade_attempt == 0.0

    def test_a_round_climbs_when_there_is_nothing_to_hand_down(self):
        primary = Service("primary")
        failover, clock, _ = build([primary, Service("standby")])
        failover._switch_to_next()
        clock.advance(301)

        failover._run_check()

        assert failover.get_current_service_name() == "primary"

    def test_a_round_climbs_when_the_probe_on_the_active_service_raises(self):
        # A probe that raises answers nothing, and nothing is not a
        # demotion. Reported as one, it takes the climb with it -- the
        # round skips the climb whenever the work moved -- so a chain whose
        # active service cannot be probed at all never comes back up, and
        # the standby keeps work the primary is well enough to do. The
        # shape that survives everything else is the `except` branch of
        # `_attempt_demotion` answering True.
        def explode(service):
            if service.name == "worst":
                raise RuntimeError("probe exploded")
            return service.healthy

        failover, clock, _ = build(
            [Service("best"), Service("worst")], health_checker=explode
        )
        failover._switch_to_next()
        clock.advance(301)

        failover._run_check()

        assert failover.get_current_service_name() == "best"

    def test_a_round_climbs_past_a_service_that_cannot_be_handed_down(self):
        # Unwell, and nothing below it to take the work: the demotion fails,
        # so the climb still runs -- and finds a healthy service above.
        failover, clock, _ = build([
            Service("best"),
            Service("worst", healthy=False),
        ])
        failover._switch_to_next()
        clock.advance(301)

        failover._run_check()

        assert failover.get_current_service_name() == "best"


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

    def test_the_thread_hands_the_work_down_on_its_own(self):
        # The other direction through the same seam, and the one with no
        # other way of happening at all: nothing in the application calls
        # `_attempt_demotion`, and the service being demoted here never
        # raises -- it only answers that it is unwell, as a logger without
        # handlers does.
        primary = Service("primary")
        failover, _, _ = build(
            [primary, Service("standby")], check_interval=0.01
        )
        try:
            assert failover.execute("speak") == "primary spoke"

            primary.healthy = False

            assert wait_until(
                lambda: failover.get_current_service_name() == "standby"
            ), "the thread never handed the work down"
            assert failover.execute("speak") == "standby spoke"
        finally:
            failover.shutdown()

    def test_a_round_that_throws_does_not_take_the_thread_with_it(self):
        # The thread is the only caller of either check, so losing it
        # freezes the work where it stands -- and nothing would say so:
        # `shutdown()` reports the same clean stop either way. The round is
        # counted and the thread goes on to the next one.
        #
        # The throw comes from the round rather than from its logger. A
        # logger cannot do it any more -- every line goes through `_say`,
        # which absorbs -- so what a logger raising here would measure is
        # `_say`, not this loop. `_run_check` is overridden rather than
        # patched afterwards because the thread starts inside `__init__`
        # and would otherwise get a round or two in first.
        primary = Service("primary", healthy=False)
        standby = Service("standby", healthy=False)
        failover = RoundsThatExplode(
            services=[(primary, "primary"), (standby, "standby")],
            explosions=2,
            check_interval=0.01,
            health_checker=health_of,
            logger=RecordingLogger(),
            clock=FakeClock(),
        )
        try:
            # A bound from below, and it is meant as one: it says that
            # rounds go on being counted after the first, which a counter
            # assigned instead of incremented never manages. What the
            # number is exactly is read against a literal in the test
            # below, where exactly one round is lost.
            assert wait_until(lambda: failover.failed_checks >= 2), (
                "the rounds were not counted one by one"
            )
            # Still taking rounds, not merely still breathing: a standby
            # that recovers is picked up by one of the rounds that follow.
            standby.healthy = True
            assert wait_until(
                lambda: failover.get_current_service_name() == "standby"
            ), "the thread died with the round"
        finally:
            failover.shutdown()

    def test_one_lost_round_is_reported_as_one(self):
        # The check above bounds the count from below, and three separate
        # mutations of this arithmetic lived under that bound: adding two
        # per round, reading the count before the increment so the line
        # understates it, and a property returning one more than was
        # counted. Exactly one round is lost here, so the counter and the
        # line it prints can both be read against a literal.
        logger = RecordingLogger()
        failover = RoundsThatExplode(
            services=[(Service("primary", healthy=False), "primary"),
                      (Service("standby", healthy=False), "standby")],
            explosions=1,
            check_interval=0.01,
            health_checker=health_of,
            logger=logger,
            clock=FakeClock(),
        )
        try:
            # Waited out on the line rather than on the counter. Waiting on
            # the counter asks the very property under test whether the
            # test may proceed: a property that adds one to what it counted
            # answers "1" before a single round has run, and the assertion
            # below then reads that same 1 and passes -- re-measured
            # 2026-08-10 on an off-by-one property, 20 runs in 20.
            assert wait_until(
                lambda: any("rounds lost so far" in said
                            for said in logger.warnings)
            ), "the lost round was never announced"
            assert failover.failed_checks == 1
            assert any(
                "(1 rounds lost so far)" in said for said in logger.warnings
            ), "the line and the counter disagree about how much was lost"
        finally:
            failover.shutdown()


    def test_shutdown_stops_the_thread_before_it_returns(self):
        # `shutdown()` joins the thread itself, so a caller that has been
        # told the service is down may rely on it. A test that does its own
        # join afterwards would measure its own patience instead.
        failover, _, _ = build([Service("primary")], check_interval=0.01)
        assert failover._thread.is_alive()

        assert failover.shutdown() is True

        assert failover._thread.is_alive() is False

    def test_the_thread_waits_the_interval_out_between_rounds(self):
        # A loop that stopped waiting would spin a core and put a probe --
        # which writes a record -- through the logging stack as fast as it
        # can. Nothing in the suite fails on that; only its own runtime
        # grows, without bound: re-measured 2026-08-10, `tests/unit` takes
        # 7.9 s as written and did not finish within 600 s with the wait
        # replaced by `is_set()`.
        rounds = []

        def counting_probe(service):
            rounds.append(service.name)
            return service.healthy

        failover, _, _ = build(
            [Service("primary"), Service("standby")],
            check_interval=0.05,
            health_checker=counting_probe,
        )
        try:
            time.sleep(0.3)
        finally:
            failover.shutdown()

        # Six rounds fit into 0.3 s at this interval. The ceiling is
        # generous for a loaded machine and still far under a busy loop,
        # which manages thousands; the floor is what proves it ran at all.
        assert 1 <= len(rounds) <= 30, f"{len(rounds)} rounds in 0.3 s"

    def test_shutdown_does_not_wait_longer_than_its_default(self):
        # The wait has a ceiling as well as a floor. Raised, every shutdown
        # of the application queues behind a probe that is not coming back.
        entered = threading.Event()
        release = threading.Event()

        def probe(service):
            entered.set()
            release.wait(10)
            return True

        failover, _, _ = build(
            [Service("primary"), Service("standby")],
            check_interval=0.01,
            health_checker=probe,
        )
        try:
            assert entered.wait(2.0), "the probe was never reached"
            begin = time.monotonic()
            assert failover.shutdown() is False
            waited = time.monotonic() - begin
        finally:
            release.set()
            failover.shutdown()

        assert waited < 2.0, f"shutdown waited {waited:.1f}s by default"

    def test_shutdown_says_so_when_the_thread_does_not_stop(self):
        # A join that timed out and a join that succeeded return the same
        # None, so the caller has to be told apart from the outside.
        entered = threading.Event()
        release = threading.Event()

        def probe(service):
            entered.set()
            release.wait(5)
            return True

        failover, _, logger = build(
            [Service("primary"), Service("standby")],
            check_interval=0.01,
            health_checker=probe,
        )
        try:
            assert entered.wait(2), "the probe was never reached"

            assert failover.shutdown(timeout=0.05) is False
            assert logger.warnings[-1] == (
                "The health check thread did not stop within 0.05s"
            )
        finally:
            release.set()
            failover.shutdown()

    def test_shutdown_is_safe_when_no_thread_was_started(self):
        failover, _, _ = build([Service("primary")], check_interval=None)
        assert failover.shutdown() is True
        assert failover._stop_event.is_set()

    def test_shutdown_twice_is_not_an_error(self):
        # Both managers forward shutdown from the DI lifecycle, which can
        # run more than once.
        failover, _, _ = build([Service("primary")], check_interval=0.01)
        failover.shutdown()
        failover.shutdown()
        assert failover._thread.is_alive() is False


class TestEveryServiceIsAskedBeforeTheCallIsGivenUp:
    """
    The loop bounds itself by the services it asked, not by turns taken.

    While it counted attempts the two came apart the moment anything else
    moved the index: a turn spent re-asking a service already asked used
    up the same budget as a turn that reached a new one, and the budget
    ran out early. In production the chain is two implementations long,
    where the shapes below cannot arise -- but the class is written for
    any number, and the third one would meet them in silence.
    """

    class MovesTheIndexThenFails(Service):
        """A service that fails after the ground has shifted under it.

        Standing in for a background round that demoted or promoted
        between two turns of the loop. Doing it from inside the call is
        what makes the race deterministic; under the GIL a real thread
        would win it only sometimes.
        """

        def __init__(self, name, failover_holder, new_index):
            super().__init__(name, broken=True)
            self.failover_holder = failover_holder
            self.new_index = new_index

        def speak(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            self.failover_holder[0]._current_index = self.new_index
            raise RuntimeError(f"{self.name} is down")

    def test_the_last_service_is_reached_after_the_index_went_back(self):
        """The measured shape: a=2, b=1, c=0.

        The index moves back to the top between two turns -- an upgrade
        round taking the work home while this call is failing its way
        down. Counting turns, the loop then spends its third and last on
        ``first`` a second time and gives up without ever asking ``last``.
        """
        holder = []
        first = Service("first", broken=True)
        middle = self.MovesTheIndexThenFails("middle", holder, new_index=0)
        last = Service("last", broken=True)

        failover, _, _ = build([first, middle, last])
        holder.append(failover)

        result = failover.execute("speak", "a record")

        assert len(last.calls) == 1, "the third service was never asked"
        assert len(first.calls) == 1
        assert len(middle.calls) == 1
        assert result is ALL_SERVICES_FAILED

    def test_a_service_below_still_answers_after_the_index_went_back(self):
        """And when the one never reached would have answered."""
        holder = []
        first = Service("first", broken=True)
        middle = self.MovesTheIndexThenFails("middle", holder, new_index=0)
        last = Service("last")

        failover, _, _ = build([first, middle, last])
        holder.append(failover)

        assert failover.execute("speak") == "last spoke"

    def test_no_service_is_asked_twice_by_one_call(self):
        """A repeat is not merely wasteful.

        These are log writes: asking the same broken implementation again
        duplicates whatever side effect it managed before it threw.
        """
        holder = []
        first = Service("first", broken=True)
        middle = self.MovesTheIndexThenFails("middle", holder, new_index=0)
        last = Service("last", broken=True)

        failover, _, _ = build([first, middle, last])
        holder.append(failover)

        failover.execute("speak")

        assert len(first.calls) == 1
        assert len(middle.calls) == 1
        assert len(last.calls) == 1


# ===========================================================================
# Saying it without throwing for it: _say()
# ===========================================================================

class ThrowingLogger:
    """A logger that refuses every line, as a full disk makes one do."""

    def __init__(self, error=None):
        """
        Args:
            error: Exception to raise. ``ENOSPC`` by default, which is the
                shape this guard exists for.
        """
        self.error = error or OSError(28, "No space left on device")
        self.attempts = []

    def info(self, message: str) -> None:
        self.warning(message)

    def warning(self, message: str) -> None:
        self.attempts.append(message)
        raise self.error

    def error_(self, message: str) -> None:
        self.warning(message)


class TestALoggerThatThrowsIsNotTheCallersProblem:
    """The class exists so a failing log does not reach the caller.

    Its own logger is the hole in that: called directly, an ``ENOSPC``
    from ``self.logger`` leaves ``execute`` and arrives at whichever request
    thread was only trying to write a line -- the ``OSError`` reaches the
    caller and ``dropped_calls`` stands at zero, so the loss is neither
    absorbed nor counted.
    """

    def test_a_dropped_call_answers_the_caller_rather_than_raising(self):
        logger = ThrowingLogger()
        failover, _, _ = build([Service("only", broken=True)], logger=logger)

        result = failover.execute("speak")

        assert result is ALL_SERVICES_FAILED
        assert failover.dropped_calls == 1

    def test_the_lines_the_logger_refused_are_counted(self):
        logger = ThrowingLogger()
        failover, _, _ = build([Service("only", broken=True)], logger=logger)

        failover.execute("speak")

        # Two lines: the service that failed, and the call nobody took.
        assert logger.attempts == [
            "Service only failed for speak: only is down. Attempting switch.",
            "No service handled speak; the call was dropped (1 so far)",
        ]
        assert failover.lost_log_lines == 2

    def test_a_refused_line_goes_to_stderr(self, capsys):
        logger = ThrowingLogger()
        failover, _, _ = build([Service("only")], logger=logger)

        failover._say("the standby took over")

        assert "the standby took over" in capsys.readouterr().err

    def test_a_line_the_logger_took_is_not_repeated_on_stderr(self, capsys):
        failover, _, logger = build([Service("only")])

        failover._say("the standby took over")

        assert logger.warnings == ["the standby took over"]
        assert capsys.readouterr().err == ""
        assert failover.lost_log_lines == 0

    def test_stderr_failing_too_is_silence_and_not_a_raise(self, capsys):
        logger = ThrowingLogger()
        failover, _, _ = build([Service("only")], logger=logger)
        failover._stderr_logger = ThrowingLogger()

        failover._say("nowhere left to put this")

        assert capsys.readouterr().err == ""
        # The count is what is left of the line when both refused it.
        assert failover.lost_log_lines == 1

    def test_a_keyboard_interrupt_from_the_logger_still_stops_the_process(self):
        """``except Exception``, not a bare one: Ctrl-C keeps working.

        A guard that swallowed ``BaseException`` would make the failover
        service the one place in the application Ctrl-C does not reach.
        """
        failover, _, _ = build(
            [Service("only")], logger=ThrowingLogger(KeyboardInterrupt())
        )

        with pytest.raises(KeyboardInterrupt):
            failover._say("interrupt me")

    def test_shutdown_reports_the_timeout_rather_than_raising(self):
        """The last unprotected line was on the way out of the process.

        ``shutdown`` warns when the thread outlives the wait, and that
        warning went through ``self.logger`` directly -- so a broken logger
        turned a slow thread into an exception thrown at whatever was
        closing the application down.
        """
        started = threading.Event()

        def blocks(_service):
            started.set()
            time.sleep(0.3)
            return True

        logger = ThrowingLogger()
        failover = FailoverService(
            services=[(Service("only"), "only")],
            check_interval=0.01,
            health_checker=blocks,
            logger=logger,
        )
        assert started.wait(1.0), "the background thread never ran a check"

        assert failover.shutdown(timeout=0.01) is False
        assert failover.lost_log_lines >= 1


class TestReadingTheCountersWaitsForNothing:
    """
    The counters answer while a check is in flight.

    Their reader is ``GET /api/v1/admin/health``, and the background round
    holds this service's lock for as long as a health probe takes -- which
    since that probe became a real write is a write to disk. Taking the
    lock to read one integer put the endpoint that reports on the logging
    chain behind that chain's own disk, and outside the time budget the
    rest of its answer is bounded by: measured at 2.80 s with a probe
    holding the lock, against a ``HEALTH_CHECK_TIMEOUT`` of 5 s that does
    not cover this half of the answer at all.
    """

    def _service(self):
        """Return a service whose background thread never runs."""
        return FailoverService(
            services=[(Service("only"), "only")],
            check_interval=None,
            logger=RecordingLogger(),
        )

    def test_the_counters_answer_while_somebody_holds_the_lock(self):
        failover = self._service()
        held = threading.Event()
        release = threading.Event()

        def hold():
            with failover._lock:
                held.set()
                release.wait(5.0)

        holder = threading.Thread(target=hold, daemon=True)
        holder.start()
        try:
            assert held.wait(1.0), "the lock was never taken"

            started = time.monotonic()
            counters = (
                failover.dropped_calls,
                failover.failed_checks,
                failover.lost_log_lines,
                failover.get_current_service_name(),
            )
            waited = time.monotonic() - started

            assert counters == (0, 0, 0, "only")
            assert waited < 1.0, f"the read waited {waited:.2f}s for the lock"
        finally:
            release.set()
            holder.join(timeout=2.0)
            failover.shutdown()

    def test_what_the_counters_report_is_still_what_happened(self):
        """The premise: a read that waits for nothing still reads.

        Without this the assertions above are satisfied by properties
        that answer zero whatever the service has been through.
        """
        failover = FailoverService(
            services=[(Service("broken", broken=True), "broken")],
            check_interval=None,
            logger=RecordingLogger(),
        )
        try:
            failover.execute("speak")

            assert failover.dropped_calls == 1
        finally:
            failover.shutdown()
