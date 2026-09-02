"""
What the managers tell the ``FailoverService`` to do, and what they hand out.

``test_chain_composition`` asks which implementations a mode puts in the
chain. This file asks about the four decisions the managers make *around*
that list, none of which anything else reads. Each of the four, mutated on
its own, passes everything else in the suite:

* ``AuditManager.get_audit_logger`` returning ``_active_audit_logger``
  instead of the proxy. With failover built that attribute is never set,
  so in the default production mode it is ``None`` -- and every link
  created and every link followed answers 500;
* the health checker replaced by one that always answers ``True``, which
  is the way down removed. The failure this class exists for is exactly
  the one that raises nothing: an implementation that stops writing and
  says so only when asked;
* ``check_interval=None``, which starts no background thread, so work
  handed down never comes back up;
* an upgrade cooldown of 30 seconds where the chain promises five minutes.

None of it was reached because of the configuration rather than the tests:
every test configuration switches logging and auditing off
(``LOGGING_ENABLED = False``, ``AUDIT_ENABLED = False`` in all three
conftests), so nothing reaches this branch *through the application*. Two
files build a manager directly -- ``test_chain_composition``, which asks
what is in the chain, and ``test_logging_health``, which asks whether a
round leaves the work alone -- and between them they left the four
decisions above unasked.

What is done here is the shape Google's SRE book calls a configuration
test in its chapter on testing for reliability -- read what the thing was
actually configured with, rather than trusting the file meant to configure
it -- shrunk to what a unit test can reach: build the managers the way the
DI container builds them in production and ask what they wired.

The implementations are replaced inside the built chain, not around it.
What is under test is the manager's own wiring -- the probe it installed,
the interval and the cooldown it passed -- and a real ``StandardLogger``
answers a probe according to the handlers it can reach
(``logger.hasHandlers()``), which would make these tests about
``setup_logging`` instead.
"""

import time

import pytest

from link_shortener.infrastructure.logging.managers.audit_manager import (
    AuditManager,
)
from link_shortener.infrastructure.logging.managers.logger_manager import (
    LoggerManager,
)


# ===========================================================================
# Test doubles
# ===========================================================================

class FakeClock:
    """A clock the test moves by hand.

    Starts at a realistic epoch for the reason
    ``test_failover_service`` gives: "never attempted" is recorded inside
    the service as ``0.0``, and a clock starting near zero would read that
    as an attempt made moments ago.
    """

    def __init__(self, now: float = 1_700_000_000.0):
        """
        Args:
            now: Starting time in seconds.
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


class Implementation:
    """
    Stands in for one implementation inside a manager's chain.

    Answers both ports: the log levels ``FailoverLoggerProxy`` forwards and
    the events ``FailoverAuditLoggerProxy`` forwards, so one double serves
    either manager.

    Attributes:
        name: Identifies the instance in assertions.
        healthy: What it answers when probed.
        calls: Everything it was asked, as ``(method, args, kwargs)``.
        probes: How many times it was probed.
    """

    def __init__(self, name: str = "implementation", healthy: bool = True):
        """
        Args:
            name: Identifies the instance in assertions.
            healthy: What ``is_healthy`` answers.
        """
        self.name = name
        self.healthy = healthy
        self.calls = []
        self.probes = 0

    def __getattr__(self, method_name: str):
        """
        Record any log level or audit event asked of this double.

        Args:
            method_name: Name the proxy forwarded under.

        Returns:
            A callable that records the call and answers nothing, as the
            real log and audit methods do.
        """
        def record(*args, **kwargs):
            self.calls.append((method_name, args, kwargs))
            return None

        return record

    def is_healthy(self) -> bool:
        """Report health the way both ports do, and count the question."""
        self.probes += 1
        return self.healthy


def logger_manager(interval):
    """
    Build a ``LoggerManager`` in the mode production defaults to.

    Args:
        interval: Seconds between background checks, or ``None`` for no
            background thread.

    Returns:
        The manager.
    """
    return LoggerManager(logger_type="auto", failover_check_interval=interval)


def audit_manager(interval):
    """
    Build an ``AuditManager`` in the mode production defaults to.

    Args:
        interval: Seconds between background checks, or ``None`` for no
            background thread.

    Returns:
        The manager.
    """
    return AuditManager(audit_type="auto", failover_check_interval=interval)


BOTH_MANAGERS = [
    pytest.param(logger_manager, id="logger"),
    pytest.param(audit_manager, id="audit"),
]


@pytest.fixture
def running():
    """
    Collect managers built by a test and stop their threads afterwards.

    A manager given an interval starts a daemon thread in its constructor.
    With the fixture emptied, four ``_periodic_check`` threads are still
    running at the end of the session, one per manager that does not stop
    its own. (The twelve that ``test_chain_composition`` used
    to leave are counted where they were left, in that file.)

    Yields:
        The list to append built managers to.
    """
    built = []

    yield built

    for manager in built:
        manager.shutdown()


# ===========================================================================
# What the manager hands to the application
# ===========================================================================

class TestWhatTheManagersHandOut:
    """The mutation that answers 500 on the two busiest routes.

    Both managers choose between a proxy over the chain and a wrapper over
    the single implementation, and with a chain built there is no single
    implementation to wrap.
    """

    def test_the_mode_production_defaults_to_leaves_no_single_logger(self):
        # The premise of the test below, and the reason returning
        # `_active_audit_logger` is not a near miss but a `None`: with a
        # chain built, the attribute for the one-implementation case is
        # never assigned.
        manager = AuditManager(audit_type="auto", failover_check_interval=None)

        assert manager._failover_service is not None
        assert manager._active_audit_logger is None

    def test_the_audit_logger_it_hands_out_reaches_the_chain(self):
        manager = AuditManager(audit_type="auto", failover_check_interval=None)
        implementation = Implementation()
        manager._failover_service._services = [(implementation, "recorder")]

        manager.get_audit_logger().log_url_created(
            "abc123", "https://example.com"
        )

        assert implementation.calls == [
            ("log_url_created", ("abc123", "https://example.com"), {})
        ]

    def test_the_logger_it_hands_out_reaches_the_chain(self):
        """The same wiring on the other manager, which has its own line.

        ``LoggerManager.get_logger`` picks between a proxy over the chain
        and a wrapper over the single implementation, and the single one
        is ``None`` here too.
        """
        manager = LoggerManager(logger_type="auto", failover_check_interval=None)
        implementation = Implementation()
        manager._failover_service._services = [(implementation, "recorder")]

        manager.get_logger("web.api").info("hello")

        method, args, kwargs = implementation.calls[0]
        assert method == "info"
        assert args == ("hello",)
        assert kwargs["module"] == "web.api"


# ===========================================================================
# The probe the manager installs
# ===========================================================================

@pytest.mark.parametrize("build", BOTH_MANAGERS)
class TestTheProbeTheManagersInstall:
    """A checker that always answers well is the way down removed.

    Nothing else can take it: an implementation that has stopped writing
    raises nothing at the call site, which is why ``is_healthy`` is asked
    at all.
    """

    def test_an_implementation_that_reports_itself_unwell_hands_the_work_on(
        self, build
    ):
        manager = build(None)
        service = manager._failover_service
        service._services = [
            (Implementation("primary", healthy=False), "primary"),
            (Implementation("standby", healthy=True), "standby"),
        ]

        service._run_check()

        assert service.get_current_service_name() == "standby"

    def test_one_that_answers_for_itself_keeps_the_work(self, build):
        # The other half of the probe's job, and the quieter one: a round
        # that moves the work off an implementation which answered for
        # itself is a chain that walks down its own list for no reason.
        #
        # This one does not distinguish a probe answering False
        # everywhere -- measured: with the checker replaced by
        # `return False` it still passes, because `_attempt_demotion`
        # moves the work only onto a candidate that answers, and with that
        # mutation none does. What catches that mutation is the test above
        # (the demotion never happens) and the one below (the probe stops
        # asking the implementation).
        manager = build(None)
        service = manager._failover_service
        service._services = [
            (Implementation("primary", healthy=True), "primary"),
            (Implementation("standby", healthy=True), "standby"),
        ]

        service._run_check()

        assert service.get_current_service_name() == "primary"

    def test_the_probe_asks_the_implementation_itself(self, build):
        # Not a checker that answers out of its own head: the answer has
        # to come from the object holding the handlers.
        manager = build(None)
        service = manager._failover_service
        implementation = Implementation("primary", healthy=False)

        assert service._health_checker(implementation) is False
        assert implementation.probes == 1


# ===========================================================================
# The background checker
# ===========================================================================

class TestTheBackgroundCheckerIsStarted:
    """Without the thread there is no way back up the chain at all.

    A call that throws hands the work down from any request thread; the
    climb happens nowhere but here.
    """

    @pytest.mark.parametrize("build", BOTH_MANAGERS)
    def test_a_manager_given_an_interval_checks_without_being_asked(
        self, build, running
    ):
        manager = build(0.01)
        running.append(manager)
        service = manager._failover_service
        chain = [Implementation("primary"), Implementation("standby")]
        service._services = [(chain[0], "primary"), (chain[1], "standby")]

        # Both are counted, not just the first. The thread is already
        # running when the doubles go in -- the constructor starts it --
        # so a round may have moved the index before the swap, and which
        # of the two is probed afterwards is not the question here.
        #
        # Waited for rather than slept through: the check is due after one
        # interval, and the deadline is only reached when no thread was
        # started at all.
        deadline = time.monotonic() + 2.0
        while (
            chain[0].probes + chain[1].probes == 0
            and time.monotonic() < deadline
        ):
            time.sleep(0.005)

        assert chain[0].probes + chain[1].probes > 0

    @pytest.mark.parametrize("build", BOTH_MANAGERS)
    def test_the_interval_it_was_given_is_the_one_it_uses(self, build, running):
        manager = build(0.01)
        running.append(manager)

        assert manager._failover_service._check_interval == 0.01

    def test_the_thread_is_a_daemon_so_it_cannot_hold_the_process_up(self):
        # The DI lifecycle calls `shutdown`, and a process that dies
        # before it gets there must still be able to exit.
        manager = audit_manager(30.0)
        try:
            assert manager._failover_service._thread.daemon is True
        finally:
            manager.shutdown()


# ===========================================================================
# The upgrade cooldown
# ===========================================================================

@pytest.mark.parametrize("build", BOTH_MANAGERS)
class TestTheUpgradeCooldownTheManagersSet:
    """Five minutes, and the numbers below are written out rather than read
    from the source: a test comparing the cooldown against the constant it
    was built from moves with any change to it and holds nothing.
    """

    def _chain_on_the_standby(self, manager):
        """
        Put the work on the standby with an upgrade just attempted.

        Args:
            manager: The manager whose chain is being set up.

        Returns:
            Tuple of (failover service, clock).
        """
        service = manager._failover_service
        clock = FakeClock()
        service._clock = clock
        service._services = [
            (Implementation("primary", healthy=True), "primary"),
            (Implementation("standby", healthy=True), "standby"),
        ]
        service._switch_to_next()
        service._last_upgrade_attempt = clock()
        return service, clock

    def test_the_work_does_not_come_back_before_five_minutes(self, build):
        service, clock = self._chain_on_the_standby(build(None))

        clock.advance(299)
        service._run_check()

        assert service.get_current_service_name() == "standby"

    def test_it_comes_back_once_five_minutes_have_passed(self, build):
        # The other side of the same window: a cooldown that never lets go
        # would pass the test above and leave the primary unused forever.
        service, clock = self._chain_on_the_standby(build(None))

        clock.advance(301)
        service._run_check()

        assert service.get_current_service_name() == "primary"


# ===========================================================================
# Shutdown
# ===========================================================================

class TestTheManagersStopWhatTheyStarted:

    @pytest.mark.parametrize("build", BOTH_MANAGERS)
    def test_shutdown_stops_the_background_thread(self, build):
        manager = build(0.01)
        thread = manager._failover_service._thread

        assert manager.shutdown() is True
        assert thread.is_alive() is False

    @pytest.mark.parametrize("build", BOTH_MANAGERS)
    def test_shutdown_is_safe_when_no_thread_was_started(self, build):
        assert build(None).shutdown() is True
