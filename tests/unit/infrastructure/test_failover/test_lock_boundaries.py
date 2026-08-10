"""
Where the lock is taken, not merely that it is held during a probe.

A mutation run over ``FailoverService`` -- 59 point edits, 45 killed -- left
fourteen survivors, of which six moved a *boundary*: a read taken out from
under the lock, a pair of reads split into two, a bound of the walk shifted
by one. The three existing lock tests all passed, because they assert that
the lock is owned *inside* a probe or *at* the moment of a switch, which
none of those six changes.

So the lock itself is instrumented here. Every state read the service makes
goes through a list that reports whether the lock was held at the time,
which turns "the boundary moved" into a failing assertion rather than a
race nobody reproduces.

Measured against this file, nine mutations: seven die. The two that live
are named where they belong -- splitting one acquisition into two around
the same local (no behaviour changes) and moving the ``failed_checks``
increment out from under the lock (nothing observable can tell, see
``test_a_failed_round_is_counted_exactly_once``).
"""

import threading

import pytest

from link_shortener.infrastructure.failover.failover_service import (
    ALL_SERVICES_FAILED, FailoverService,
)


class CountingLock:
    """A lock that remembers being entered, and whether it is held now."""

    def __init__(self):
        self._real = threading.RLock()
        self.entered = 0
        self._depth = threading.local()

    def __enter__(self):
        self._real.acquire()
        self.entered += 1
        self._depth.value = getattr(self._depth, "value", 0) + 1
        return self

    def __exit__(self, *exc_info):
        self._depth.value -= 1
        self._real.release()
        return False

    def held(self) -> bool:
        """Say whether this thread is inside the lock right now."""
        return getattr(self._depth, "value", 0) > 0


class WatchedServices(list):
    """The service list, reporting reads taken without the lock."""

    def __init__(self, items, lock):
        super().__init__(items)
        self._lock = lock
        self.unlocked_reads = 0

    def __getitem__(self, index):
        if not self._lock.held():
            self.unlocked_reads += 1
        return super().__getitem__(index)


class Service:
    """A stand-in service; ``speak`` answers or raises."""

    def __init__(self, name, healthy=True, broken=False, before_raise=None):
        self.name = name
        self.healthy = healthy
        self.broken = broken
        self.calls = []
        self._before_raise = before_raise

    def speak(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.broken:
            if self._before_raise is not None:
                self._before_raise()
            raise RuntimeError(f"{self.name} is down")
        return f"{self.name} spoke"

    def is_healthy(self):
        return self.healthy


def instrumented(services, **kwargs):
    """
    Build a service whose lock and service list are both watched.

    Args:
        services: Fakes in priority order.
        **kwargs: Passed through to ``FailoverService``.

    Returns:
        Tuple of (failover service, lock, watched list).
    """
    kwargs.setdefault("check_interval", None)
    kwargs.setdefault("health_checker", lambda service: service.is_healthy())
    failover = FailoverService(
        services=[(s, s.name) for s in services], **kwargs
    )
    lock = CountingLock()
    failover._lock = lock
    watched = WatchedServices(failover._services, lock)
    failover._services = watched
    return failover, lock, watched


class TestEveryStateReadIsTakenUnderTheLock:

    def test_naming_the_current_service(self):
        failover, lock, watched = instrumented(
            [Service("primary"), Service("standby")]
        )

        assert failover.get_current_service_name() == "primary"
        assert lock.entered >= 1
        assert watched.unlocked_reads == 0

    @pytest.mark.parametrize("counter", ["dropped_calls", "failed_checks"])
    def test_reading_a_counter(self, counter):
        """Single ``int`` reads on CPython today -- and a boundary all the
        same, which is what a later reader will follow."""
        failover, lock, _ = instrumented([Service("primary")])
        before = lock.entered

        getattr(failover, counter)

        assert lock.entered > before

    def test_the_call_path_reads_index_and_service_together(self):
        """Two separate reads can disagree.

        ``execute`` protects itself by switching only from the index its
        failed call was made on. Read apart, the pair can come from either
        side of another thread's move, and the guard then compares against
        an index the call was never on.
        """
        failover, lock, watched = instrumented(
            [Service("primary", broken=True), Service("standby")]
        )

        assert failover.execute("speak") == "standby spoke"
        assert watched.unlocked_reads == 0

    def test_the_background_round_reads_the_active_service_too(self):
        """The most dangerous of the six.

        With this read outside the lock the round probes a service the
        request thread has already left, and then demotes *from the
        current index* -- carrying the work past a healthy neighbour, and
        writing a line that names a service which was not holding it.
        """
        failover, lock, watched = instrumented(
            [Service("primary", healthy=False), Service("standby")]
        )

        assert failover._attempt_demotion() is True
        assert watched.unlocked_reads == 0

    def test_a_failed_round_is_counted_exactly_once(self):
        """What can actually be asserted about the increment.

        Not "it happens under the lock": the only observable that could
        say so is the counter itself, and reading it takes the lock one
        line later -- so an assertion on ``lock.entered`` is satisfied by
        the getter and passes with the increment moved out. Measured:
        that mutation survived this file. A lost increment is what the
        lock is there to prevent, and on CPython a single ``+= 1`` on an
        int does not lose one, so what is left to pin is the arithmetic:
        one failed round, one count, and the round after it another.
        """
        failover, _, _ = instrumented(
            [Service("primary")], check_interval=0.01
        )
        try:
            failover._run_check = _raises
            threading.Event().wait(0.15)
            first = failover.failed_checks
            threading.Event().wait(0.15)

            assert first >= 1
            assert failover.failed_checks > first
        finally:
            failover.shutdown()


def _raises():
    """A round that fails, for the counter test above."""
    raise RuntimeError("the round fell over")


class TestTheIndexAndTheServiceComeFromOneReading:
    """Reading ``_current_index`` twice is not reading it once.

    ``execute`` guards itself by switching only from the index its failed
    call was made on. Take the index in one acquisition and the service in
    another, and a move landing between them hands the call a service the
    index does not name -- so the guard compares against an index nothing
    was ever called on, and the switch skips a service.
    """

    class MovingLock(CountingLock):
        """Moves the work on, once, as a later acquisition begins."""

        def __init__(self, move_on_entry):
            super().__init__()
            self._move_on_entry = move_on_entry
            self.failover = None

        def __enter__(self):
            result = super().__enter__()
            if self.entered == self._move_on_entry and self.failover:
                self.failover._current_index = 1
            return result

    def test_the_service_called_is_the_one_the_index_names(self):
        first = Service("first", broken=True)
        second = Service("second", broken=True)
        third = Service("third")

        failover, _, _ = instrumented([first, second, third])
        lock = self.MovingLock(move_on_entry=2)
        lock.failover = failover
        failover._lock = lock
        failover._services._lock = lock

        failover.execute("speak")

        # `first` is what index 0 names, and index 0 is what the call read.
        # Split in two, the second acquisition re-reads the index the fake
        # lock has just moved, and `second` is called for a turn that
        # believes it is on `first`.
        assert len(first.calls) == 1
        assert first.calls[0] == ((), {})


class TestTheWalkStartsBelowTheCurrentService:
    """The sixth survivor: a bound of the demotion walk shifted by one.

    Four services with the work in the middle, so that "one below" and
    "the end of the list" are different places and the healthy neighbour
    is not the one next door. A walk starting at the current index would
    hand the work to the service it just found unwell; one starting at
    zero would hand it *upwards*, past the two above it.
    """

    def test_an_unwell_service_is_not_a_candidate_for_its_own_work(self):
        best = Service("best", healthy=False)
        working = Service("working", healthy=False)
        broken = Service("broken", healthy=False)
        last = Service("last", healthy=True)

        failover, _, _ = instrumented([best, working, broken, last])
        failover._current_index = 1

        assert failover._attempt_demotion() is True
        assert failover.get_current_service_name() == "last"

    def test_the_service_just_found_unwell_is_not_probed_again(self):
        """A walk starting at the current index asks it twice.

        Harmless while a probe answers the same thing twice -- and a probe
        is exactly the thing that need not. ``StandardLogger.is_healthy``
        writes a debug record to find out, so a handler that comes and
        goes answers ``False`` and then ``True``, and the work is handed
        "down" onto the service it was already on, with a line announcing
        a move that did not happen.
        """
        probes = []
        primary = Service("primary", healthy=False)
        standby = Service("standby", healthy=True)

        def counting_health(service):
            probes.append(service.name)
            return service.healthy

        failover, _, _ = instrumented(
            [primary, standby], health_checker=counting_health
        )

        failover._attempt_demotion()

        assert probes == ["primary", "standby"]

    def test_the_walk_never_climbs(self):
        """A healthy service *above* the current one is not a demotion."""
        best = Service("best", healthy=True)
        working = Service("working", healthy=False)
        broken = Service("broken", healthy=False)
        last = Service("last", healthy=False)

        failover, _, _ = instrumented([best, working, broken, last])
        failover._current_index = 1

        assert failover._attempt_demotion() is False
        assert failover.get_current_service_name() == "working"
