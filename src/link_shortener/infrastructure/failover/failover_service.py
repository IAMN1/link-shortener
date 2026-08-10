import threading
from typing import Any, Callable, Generic, List, Optional, Tuple, TypeVar
import time

from link_shortener.infrastructure.failover.minimal_logger import MinimalLogger

T = TypeVar('T')


class _AllServicesFailed:
    """
    The answer ``execute`` gives when every service refused the call.

    ``None`` cannot carry it. Every logging and every audit *record*
    method returns nothing on success, so ``None`` already means "it
    worked"; using it for "nothing worked" left an audit trail that had
    stopped recording looking exactly like one that recorded fine, and
    every audit call site discards the value. (``is_healthy`` also comes
    through here and does return something, which is why the two managers
    can go on testing it with ``is True``.)

    A distinct object is the ordinary remedy for a ``None`` that has to
    mean two things (PEP 661). Truthy: a falsy sentinel puts success and
    exhaustion back under one ``if not result``, which is the very
    confusion it exists to end. ``__bool__`` states that rather than
    establishing it -- an object with neither ``__bool__`` nor ``__len__``
    is true already -- so that adding either later cannot change the answer
    quietly. What does not answer is a boolean test; ``is
    ALL_SERVICES_FAILED`` is the one to write, and PEP 661 says the same
    ("identity checks ... should usually be used rather than boolean
    checks"). Printable, so it reads as itself in a log line rather than
    as an address.
    """

    __slots__ = ()

    def __bool__(self) -> bool:
        return True

    def __repr__(self) -> str:
        return "ALL_SERVICES_FAILED"

    def __reduce__(self):
        """
        Survive pickling as the same object.

        Without this the sentinel is rebuilt on the far side of a pickle
        or a deepcopy, and ``is ALL_SERVICES_FAILED`` -- the only way
        anyone is meant to test for it -- quietly answers False. Nothing
        carries it across such a boundary today, and the task queue could
        not: Celery here is configured for JSON, which refuses this object
        outright rather than rebuilding it wrongly. One line, so that a
        ``deepcopy`` of a structure that happens to hold it stays correct.

        Returns:
            The name to look up on unpickling.
        """
        return "ALL_SERVICES_FAILED"


ALL_SERVICES_FAILED = _AllServicesFailed()
"""Singleton returned by :meth:`FailoverService.execute` on exhaustion."""


class FailoverService(Generic[T]):
    """
    Failover manager for a group of interchangeable services.

    Type parameter ``T`` represents the service interface (e.g., ``Logger``,
    ``AuditLogger``). The first service in the list is considered the primary;
    subsequent entries are fallbacks.

    Background health checks move the work both ways: down when the active
    service reports itself unwell, and back up to a higher-priority one
    when it recovers.
    """

    def __init__(
        self,
        services: List[Tuple[T, str]],
        check_interval: Optional[float] = 30.0,
        health_checker: Optional[Callable[[T], bool]] = None,
        upgrade_cooldown: float = 300.0,
        logger: Optional[MinimalLogger] = None,
        clock: Callable[[], float] = time.time
    ):
        """
        Initialize the failover service.

        Args:
            services: List of ``(service_instance, service_name)`` in
                priority order (highest first). Must not be empty.
            check_interval: Seconds between background health checks.
                If ``None``, background checks are disabled.
            health_checker: Optional callable that takes a service instance
                and returns ``True`` if it is healthy. Asked by the
                background check in both directions: an unwell service
                hands the work down, a recovered one takes it back. Without
                one there is nothing to ask, so nothing is handed down, and
                an upgrade takes the work back to the highest-priority
                service as soon as the cooldown has run out -- including
                onto a service whose last call threw, which then pays for
                the guess. That is what recovery without an active probe
                is: nginx puts a server back in the pool when
                ``fail_timeout`` expires, having asked it nothing ("the
                period of time the server will be considered unavailable",
                ``ngx_http_upstream_module``). Both managers in this
                application pass a checker.
            upgrade_cooldown: Minimum seconds between upgrade attempts.
            logger: Logger for failover events. Defaults to
                ``MinimalLogger()`` which prints to stderr
            clock: Source of the current time in seconds, used for the
                upgrade cooldown. Injected so that a test can move time
                by hand: the cooldown is five minutes, and the only other
                way to observe it expiring is to wait five minutes.

        Raises:
            ValueError: If ``services`` is empty.
        """

        if not services:
            raise ValueError("At least one service required")

        self._services = services
        self._check_interval = check_interval
        self._health_checker = health_checker
        self._upgrade_cooldown = upgrade_cooldown
        self._clock = clock
        self._lock = threading.RLock()
        self._current_index = 0                 # index of currently active service
        # Epoch, meaning "never attempted". Works because a real clock reads
        # far past any cooldown; a clock starting near zero would read this
        # as an attempt made moments ago and block the first upgrade.
        self._last_upgrade_attempt = 0.0
        self._dropped_calls = 0
        self._failed_checks = 0
        self._lost_log_lines = 0

        self._stop_event = threading.Event()
        self._thread = None

        # Use provided logger or default to a simple stderr logger
        self.logger = logger if logger is not None else MinimalLogger()

        # An instance of its own rather than `self.logger`. It is reached
        # only after `self.logger` has just thrown, and asking the same
        # object a second time is asking the thing that failed.
        self._stderr_logger = MinimalLogger()

        if self._check_interval is not None:
            self._thread = threading.Thread(
                target=self._periodic_check,
                daemon=True
            )
            self._thread.start()

    def get_current_service_name(self) -> str:
        """Return the name of the currently active service"""
        with self._lock:
            return self._services[self._current_index][1]

    def _say(self, message: str) -> None:
        """
        Write one line about this service's own working, and never throw.

        Every announcement in this class goes through here. Called
        directly, ``self.logger`` took the caller with it whenever the
        logger itself was the thing that broke: a full disk raises
        ``OSError(ENOSPC)`` on the write, and the exception left
        ``execute`` -- the one method a request thread reaches -- out of
        the one class built so that a failing log does not reach the
        caller. Measured before this, on a logger raising ``ENOSPC``:
        the ``OSError`` arrived at the caller and ``dropped_calls`` stood
        at zero, so the loss was neither absorbed nor counted.

        Then stderr, then silence. That order is the standard library's
        answer to the same problem: ``Handler.handleError`` writes the
        failure to ``sys.stderr`` -- "If raiseExceptions is false,
        exceptions get silently ignored. This is what is mostly wanted
        for a logging system - most users will not care about errors in
        the logging system" -- and puts its whole diagnostic block, that
        write included, under ``except OSError: pass`` (CPython,
        ``Lib/logging/__init__.py``), because whatever stopped the logger
        commonly stops stderr too. What outlives both is the count.

        Args:
            message: The line to write.
        """
        try:
            self.logger.warning(message)
            return
        except Exception:
            with self._lock:
                self._lost_log_lines += 1

        try:
            self._stderr_logger.warning(message)
        except Exception:
            # Nowhere left to say it. The count above is what remains of
            # the line, and it is reported by `GET /api/v1/admin/health`.
            pass

    def _periodic_check(self) -> None:
        """
        Background thread: keep the work on the best service that answers for
        itself. Runs every `_check_interval` seconds until `shutdown()` is
        called.

        Down first, and then up only if nothing went down. A round that has
        just taken the work off a service has nothing left to ask: the climb
        would put the same question to the same service in the same round --
        and the answer, being ``False``, would spend the upgrade cooldown on
        it. That is five minutes booked for a probe already answered, and it
        is paid by whichever service recovers next, which waits out the
        booking instead of one check interval. Measured before this: a
        primary handed down by the probe and healthy again a moment later
        took 300 s to get the work back, against 30 s when the same demotion
        came from a call that threw.

        A round that throws costs that round and nothing more. An exception
        leaving here ends the thread, and this thread is the only thing in
        the application that ever moves the work back up -- so the failure
        would be permanent, silent, and invisible to ``shutdown()``, which
        would go on reporting a clean stop. What the standard library does
        with it is print to ``sys.stderr`` and let the thread die
        (``threading.excepthook``: "the exception is printed out on
        sys.stderr"). The line is not what is lost -- this process runs
        gunicorn in the foreground with both logs on the standard streams,
        and the failover logger writes to stderr itself -- the thread is.
        The round is counted instead, on ``failed_checks``, which survives
        even a logger that cannot say anything.
        """
        while not self._stop_event.wait(self._check_interval):
            try:
                self._run_check()
            except Exception as e:
                with self._lock:
                    self._failed_checks += 1
                    failed = self._failed_checks
                self._say(
                    f"Health check round failed: {e}. The thread stays "
                    f"up ({failed} rounds lost so far)"
                )

    def _run_check(self) -> None:
        """
        One round of the background check: down if it must, up if it may.

        Separate from the loop so that a test can take one round rather
        than start a scheduler and wait for it.
        """
        if not self._attempt_demotion():
            self._attempt_upgrade()

    def _attempt_demotion(self) -> bool:
        """
        Hand the work down when the active service reports itself unwell.

        A health check that only ever promotes is half a health check, and
        the missing half is the older one: "Client requests are not passed
        to unhealthy servers and servers in the "checking" state"
        (``ngx_http_upstream_hc_module``, the active checks of nginx Plus;
        the open build has the passive ``max_fails`` instead). Without
        this the only way down was an exception from a real call, and a
        logging implementation can stop writing without raising anything:
        ``is_healthy`` is asked whether a handler can be reached at all, and
        a ``log`` call that reaches none returns as quietly as one that
        reaches a file -- records dropped in silence, and a standby sitting
        idle next to it.

        One failed probe is enough, which is also nginx's default
        (``fails=1``). The probe here is a local call into a logging object
        rather than a request across a network, so a single ``False`` is an
        answer and not a symptom of the path to it.

        The work moves only onto a service that answers for itself, so two
        unwell services leave it where it is; a probe that raises answers
        nothing and likewise moves nothing, which is what an upgrade does
        with the same raise.

        Returns:
            True if the work was handed down, False if it was left where it
            was -- for any reason, including there being nothing to ask.
        """
        with self._lock:
            if self._health_checker is None:
                return False  # nothing to ask, and no news is not bad news

            service, name = self._services[self._current_index]
            try:
                if self._health_checker(service):
                    return False
            except Exception as e:
                self._say(f"Health check for {name} failed: {e}")
                return False

            for idx in range(self._current_index + 1, len(self._services)):
                candidate, candidate_name = self._services[idx]
                # The probe alone is guarded. With the announcement inside
                # the same `try`, a logger that threw was reported as a
                # probe that threw -- a message naming the wrong culprit.
                # `_say` no longer throws, so that misattribution is all
                # this narrow `try` still buys; it is enough.
                try:
                    answered = self._health_checker(candidate)
                except Exception as e:
                    self._say(
                        f"Health check for {candidate_name} failed: {e}"
                    )
                    continue

                if answered:
                    # Moved first and announced after, as `_switch_to_next`
                    # already does: a line saying the work moved is written
                    # once it has. This order was also what stood between a
                    # throwing logger and a lost demotion, back when the
                    # announcement was `self.logger` directly -- that part
                    # is now `_say`'s, and the order is kept because the
                    # message is about something already done.
                    self._current_index = idx
                    self._say(
                        f"Demoting from {name} to {candidate_name}: "
                        f"{name} reports itself unhealthy"
                    )
                    return True

            # Only about what is below: the round is not over, and a service
            # higher up the list may still take the work in the climb that
            # follows this one.
            self._say(
                f"{name} reports itself unhealthy and nothing below it "
                f"answers"
            )
            return False

    def _attempt_upgrade(self) -> None:
        """
        Try to switch to a service with higher priority (lower index) if it is healthy.
        If a healthy higher-priority service is found, switch to it and log the event.

        The cooldown is spent only where there is something to spend it on.
        Stamping it before the "already on the best one" exit meant every
        routine check on a healthy primary -- which is nearly all of them --
        reserved the next five minutes for an attempt that never happened,
        so a service that broke just after such a check waited out the whole
        cooldown instead of one interval.

        It is spent once, and an upgrade does not give it back. Clearing the
        stamp after a successful climb -- so that the next one could go
        further up the list -- made every later attempt unconditional, and
        the loop below already goes as far up as it can: it walks the list
        from the top, so one attempt lands on the best healthy service there
        is. What the clearing left was a promotion repeatable at every check.
        Measured on the production shape, two services and a health checker
        that calls the primary well while its calls still throw: the work
        went back up six times in 180 seconds against a five-minute
        cooldown, falling straight back each time. The half-open trial of
        a circuit breaker is charged the same way when it fails ("If any
        request fails ... It restarts the time-out timer", Azure
        Architecture Center, Circuit Breaker pattern); it is not charged
        for a trial that succeeds, and that is the difference. A breaker
        that closes has the whole service back and nothing left to wait
        for. An upgrade here is a guess: the probe asked whether the
        service is well, not whether the calls it is about to take will
        work, and the six climbs above were all made on a probe answering
        yes.
        """
        with self._lock:
            if self._current_index == 0:
                return # already the best

            # Under the lock along with the index it is read against. Not
            # against a second checker -- one thread runs these -- but
            # against `execute`, which moves the index from any request
            # thread there is, and against every reader of it.
            now = self._clock()
            if now - self._last_upgrade_attempt < self._upgrade_cooldown:
                return
            self._last_upgrade_attempt = now

            for idx, (service, name) in enumerate(self._services[:self._current_index]):
                # The probe alone is guarded, as in `_attempt_demotion`: a
                # logger throwing on the announcement would otherwise be
                # reported as the probe failing, naming the wrong culprit.
                try:
                    answered = (
                        self._health_checker is None
                        or self._health_checker(service)
                    )
                except Exception as e:
                    self._say(f"Health check for {name} failed: {e}")
                    continue

                if answered:
                    # Moved first and announced after, as in
                    # `_attempt_demotion`. The name is taken before the
                    # move because the message is about where the work came
                    # from. Announcing first once cost more here than a
                    # lost message: the cooldown is stamped at the top of
                    # this method, so a logger throwing on this line lost
                    # the climb and kept the booking -- measured, a healthy
                    # primary stood unused for 301 s beside a standby the
                    # work had no reason to be on. `_say` is what stands
                    # between the two now; the order stays because a line
                    # about a move belongs after the move.
                    left_behind = self._services[self._current_index][1]
                    self._current_index = idx
                    self._say(f"Upgrading from {left_behind} to {name}")
                    return

    def _switch_to_next(self) -> bool:
        """
        Switch to the service one step down the list.

        Nothing is asked of it: this is the way down taken by a call that
        threw, and the next entry is where the work goes whether or not it
        would answer a probe. Health decides the way back up, and
        ``_attempt_demotion`` is the one place it decides a way down.

        Returns:
            True if there was a service below and the work moved to it,
            False if the list was already at its end.
        """
        with self._lock:
            next_index = self._current_index + 1
            if next_index >= len(self._services):
                return False

            self._current_index = next_index
            self._say(
                f"Switched to {self._services[next_index][1]}"
            )
            return True
    
    def execute(self, method_name: str, *args, **kwargs) -> Any:
        """
        Call a method on the current active service.

        If the call fails, automatically switch to the next service and
        retry. Returns the result of the successful call, or
        ``ALL_SERVICES_FAILED`` when every service refused it.

        No ordinary exception from a wrapped service escapes -- the
        clause is ``except Exception``, so a KeyboardInterrupt still
        stops the process, which is what it is for. What runs through
        here is logging and auditing, and a logging subsystem that throws
        takes the application down with the record it was trying to write;
        the standard library takes the same view of its own handlers, whose
        errors ``Handler.handleError`` turns into a note on stderr rather
        than into an exception for the caller. The refusal is reported
        instead: distinctly in the return value, in the count on
        ``dropped_calls``, and in a log line of its own.

        Nor does the failover service's own logger escape. It used to:
        ``self.logger`` was called unprotected here, and a logger raising
        ``ENOSPC`` carried that exception out to the caller with
        ``dropped_calls`` still at zero. Every announcement now goes
        through ``_say``, which falls back to stderr and then to silence
        and counts the line on ``lost_log_lines``.

        The lock is held around the state and not around the call. Holding
        it across ``method(*args, **kwargs)`` put every thread in the
        process behind whichever one was writing: a
        ``get_current_service_name()`` -- which only reads an integer --
        waited out whatever call happened to be in flight, however long it
        took, and every line this application logs goes through here.
        ``test_a_call_in_flight_does_not_hold_up_a_reader`` holds one call
        for 0.3 s and requires the reader through in under 0.05 s.

        What the wide lock did buy was that two threads failing on the same
        service could not each switch and land the work two places down,
        past a standby that worked. That
        is bought instead by switching only from the index the failing call
        was made on: a thread that finds the index already moved retries on
        what is there now rather than moving it again. The price of the
        narrow lock is that those threads all reach the broken service
        before the first of them switches, so each pays for its own
        failure once; the wide lock made them queue for it.

        Args:
            method_name: Name of the method to call on the service.
            *args, **kwargs: Arguments to pass to the method.

        Returns:
            Result of the method call, or ``ALL_SERVICES_FAILED``.
        """
        # Which services were asked, not how many times something was
        # tried. Counting attempts made the two the same thing only while
        # the index stood still: a background round that moved it between
        # two turns of this loop spent a turn re-asking a service already
        # asked, and the count ran out before the last one was reached.
        # Measured on three implementations -- a=2, b=1, c=0 -- the call
        # came back ALL_SERVICES_FAILED having never spoken to c.
        tried = set()

        # A backstop on the loop itself. Each turn either asks a service
        # for the first time or moves the index down, and neither can
        # happen more times than there are services -- unless another
        # thread keeps moving the index out from under this one, which is
        # the one case that could spin.
        turns_left = 2 * len(self._services)

        while len(tried) < len(self._services) and turns_left > 0:
            turns_left -= 1
            with self._lock:
                index = self._current_index
                service, name = self._services[index]

            if index not in tried:
                tried.add(index)
                try:
                    method = getattr(service, method_name)
                    return method(*args, **kwargs)
                except Exception as e:
                    self._say(
                        f"Service {name} failed for {method_name}: {e}. "
                        f"Attempting switch."
                    )

            with self._lock:
                # Someone else has already moved the work on: theirs stands,
                # and this call is retried where it now points.
                if self._current_index == index and not self._switch_to_next():
                    break

        # Every service refused. Said once, in its own words: the lines
        # above report one service failing over to the next, which is
        # the normal working of this class, and read the same whether
        # or not anything caught the call in the end.
        with self._lock:
            self._dropped_calls += 1
            dropped = self._dropped_calls
        self._say(
            f"No service handled {method_name}; the call was dropped "
            f"({dropped} so far)"
        )
        return ALL_SERVICES_FAILED

    @property
    def dropped_calls(self) -> int:
        """
        How many calls no service handled.

        Counts calls, not records: an ``is_healthy`` asked through this
        service -- as the two proxies ask it -- lands here too when no
        implementation answered. That is deliberate, nothing handled it
        either, but it means the number is not a count of lost audit lines
        on its own. The background round's own probe does not reach this
        counter at all: it calls the service instance directly rather than
        through ``execute``.

        Returns:
            Count since this service was built. Non-zero means work this
            service was asked to do that nobody did.
        """
        with self._lock:
            return self._dropped_calls

    @property
    def failed_checks(self) -> int:
        """
        How many background rounds ended in an exception.

        Each one is a round that ended early, which is not the same as a
        round that did nothing. A round that throws while handing the work
        down never reaches the climb. The thread lives on, so the number
        is a rate rather than a death notice -- but it stops growing only
        when the rounds start finishing.

        Nothing routine reaches it. Probes are caught where they are made
        and announcements go through ``_say``, which does not throw, so
        the counter now stands for what the guard around ``_run_check``
        was always for: whatever this class has not thought of. A logger
        refusing a line is counted on ``lost_log_lines`` instead, and no
        longer costs the round it was written in.

        Returns:
            Count since this service was built.
        """
        with self._lock:
            return self._failed_checks

    @property
    def lost_log_lines(self) -> int:
        """
        How many lines about this service's own working its logger refused.

        Not the calls passing through ``execute`` -- those are
        ``dropped_calls`` -- but the lines this class writes about itself:
        a demotion, a climb, a call nobody took. Counted on every refusal
        by ``self.logger``, whether or not the fallback to stderr then
        caught the line, because the refusal is the part this service can
        observe: where stderr goes is the deployment's business, and in
        a container it is as likely to be the disk that just filled.

        Non-zero means the failover chain is narrating into a logger that
        is itself broken -- so the account of what the chain did is
        missing exactly when it is worth reading.

        Returns:
            Count since this service was built.
        """
        with self._lock:
            return self._lost_log_lines

    def shutdown(self, timeout: float = 1.0) -> bool:
        """
        Stop the background health check thread and wait for it to finish.

        The wait can run out, and a caller told nothing would take a thread
        still inside a health probe for a stopped one. ``join`` cannot say
        so itself -- "As join() always returns None, you must call
        is_alive() after join() to decide whether a timeout happened"
        (``threading.Thread.join``) -- so it is asked here.

        Args:
            timeout: Seconds to wait for the thread to finish.

        Returns:
            True if there is no thread or it has stopped, False if it was
            still running when the wait ran out.
        """
        self._stop_event.set()
        if self._thread is None:
            return True

        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            self._say(
                f"The health check thread did not stop within {timeout}s"
            )
            return False
        return True
