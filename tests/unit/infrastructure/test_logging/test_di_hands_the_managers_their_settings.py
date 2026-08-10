"""
The seam between the configuration and the two logging managers.

``test_managers_wire_the_failover_service`` asks what a manager does with
the settings it was given. This asks the question one step out: whether the
DI components hand it the settings the operator actually set. Nothing did,
because every test configuration switches logging and auditing off, so the
component's own branch -- the one that builds a manager at all -- is not
reached by the suite through the application.

Measured against the whole suite, each mutation on its own, all four left
it green:

* ``LoggerComponent`` and ``AuditComponent`` passing
  ``failover_check_interval=None``. No background thread starts, so an
  implementation that reports itself unwell keeps the work and one that
  recovers never gets it back -- while the chain, the counters and the
  health body all look exactly as configured;
* ``AuditComponent`` building a fresh manager per call instead of keeping
  the one it built. Every audit event then gets a new ``FailoverService``
  and a new daemon thread that nobody stops, ``self._manager`` stays
  ``None`` so the health body reports the audit chain as never started,
  and a demotion is forgotten between one event and the next;
* the container reading ``LOGGING_ENABLED`` where it means
  ``AUDIT_ENABLED``. An operator who switched auditing off gets the full
  trail -- ``original_url``, ``remote_addr``, ``user_id`` -- and one who
  switched logging off silently loses the audit trail instead.

The components are built directly rather than through a container: what is
under test is what they pass on, and the container is asked separately for
the one thing only it decides, which flag goes where.
"""

import pytest

from link_shortener.infrastructure.di.components.audit import AuditComponent
from link_shortener.infrastructure.di.components.logger import LoggerComponent


def logger_component(enabled=True, interval=None):
    """
    Build a ``LoggerComponent`` in the mode production defaults to.

    Args:
        enabled: The ``LOGGING_ENABLED`` flag.
        interval: Seconds between background checks.

    Returns:
        The component.
    """
    return LoggerComponent(
        logging_enabled=enabled,
        logger_type="auto",
        failover_check_interval=interval,
    )


def audit_component(enabled=True, interval=None):
    """
    Build an ``AuditComponent`` in the mode production defaults to.

    Args:
        enabled: The ``AUDIT_ENABLED`` flag.
        interval: Seconds between background checks.

    Returns:
        The component.
    """
    return AuditComponent(
        audit_enabled=enabled,
        audit_type="auto",
        failover_check_interval=interval,
    )


def chain_of(component):
    """
    Reach the failover service the component's manager built.

    Args:
        component: A ``LoggerComponent`` or ``AuditComponent`` that has
            already been asked for a logger.

    Returns:
        The ``FailoverService``, or ``None`` when one implementation was
        enough.
    """
    return component._manager._failover_service


class TestTheIntervalReachesTheManager:

    def test_the_logger_component_passes_the_one_it_was_given(self):
        component = logger_component(interval=17.0)
        component.get_logger("web.api")

        assert chain_of(component)._check_interval == 17.0

    def test_the_audit_component_passes_the_one_it_was_given(self):
        component = audit_component(interval=19.0)
        component.get_audit_logger()

        assert chain_of(component)._check_interval == 19.0

    @pytest.mark.parametrize("build, ask", [
        pytest.param(logger_component, "get_logger", id="logger"),
        pytest.param(audit_component, "get_audit_logger", id="audit"),
    ])
    def test_a_component_given_an_interval_starts_the_checker(
        self, build, ask
    ):
        """The thread is the only way work ever comes back up the chain.

        Args:
            build: Factory for the component under test.
            ask: The method that builds the manager.
        """
        component = build(interval=30.0)
        getattr(component, ask)(
            *(["web.api"] if ask == "get_logger" else [])
        )
        try:
            thread = chain_of(component)._thread

            assert thread is not None
            assert thread.is_alive() is True
        finally:
            component.shutdown()


class TestTheManagerIsBuiltOnceAndKept:
    """A component that rebuilds leaks a thread per call and forgets."""

    def test_the_logger_component_keeps_its_manager(self):
        component = logger_component()
        component.get_logger("web.api")
        first = component._manager

        component.get_logger("web.other")

        assert component._manager is first

    def test_the_audit_component_keeps_its_manager(self):
        component = audit_component()
        component.get_audit_logger()
        first = component._manager

        component.get_audit_logger()

        assert component._manager is first

    def test_a_demotion_is_remembered_between_audit_events(self):
        """What a rebuilt manager loses, said as behaviour rather than
        as identity: the chain forgets it moved and asks the broken
        implementation again for the very next record."""
        component = audit_component()
        component.get_audit_logger()
        chain_of(component)._current_index = 1

        component.get_audit_logger()

        assert chain_of(component)._current_index == 1

    def test_the_audit_component_reports_a_chain_it_has_built(self):
        """``_manager`` left at ``None`` reads as "never started" on
        ``GET /api/v1/admin/health`` for the whole life of the process."""
        component = audit_component()
        component.get_audit_logger()

        assert component._manager is not None


class TestTheFlagSwitchesItsOwnChainOff:

    def test_logging_off_leaves_one_implementation_and_no_failover(self):
        component = logger_component(enabled=False)
        component.get_logger("web.api")

        assert component._manager._failover_service is None
        assert type(component._manager._active_logger).__name__ == "NullLogger"

    def test_auditing_off_leaves_one_implementation_and_no_failover(self):
        component = audit_component(enabled=False)
        component.get_audit_logger()

        assert component._manager._failover_service is None
        assert (
            type(component._manager._active_audit_logger).__name__
            == "NullAuditLogger"
        )

    def test_logging_on_builds_the_chain(self):
        # The premise: a component that answered "null" to everything
        # would pass both tests above.
        component = logger_component(enabled=True)
        component.get_logger("web.api")

        assert component._manager._failover_service is not None

    def test_auditing_on_builds_the_chain(self):
        component = audit_component(enabled=True)
        component.get_audit_logger()

        assert component._manager._failover_service is not None


class TestTheContainerGivesEachComponentItsOwnFlag:
    """The one thing only the container decides, and it is two words apart.

    Measured: ``audit_enabled=self.config.LOGGING_ENABLED`` left the whole
    suite green. Both directions cost something. An operator who set
    ``AUDIT_ENABLED=false`` and left logging on gets the full audit trail
    anyway -- ``original_url``, ``remote_addr`` and ``user_id`` written
    down after they asked for none of it; one who switched logging off
    loses the audit trail they never asked to lose.

    Asked with the two flags set opposite ways round, because with both
    true or both false the swap is invisible.
    """

    def _container(self, logging_enabled, audit_enabled):
        """
        Build a container over a configuration detached from the machine.

        Args:
            logging_enabled: The ``LOGGING_ENABLED`` flag.
            audit_enabled: The ``AUDIT_ENABLED`` flag.

        Returns:
            The container.
        """
        from link_shortener.infrastructure.configs.app.testing import (
            TestingConfig,
        )
        from link_shortener.infrastructure.di.container import Container

        config = type("DetachedConfig", (TestingConfig,), {
            # The fields read the environment otherwise, and this test
            # would then measure the machine it runs on.
            "IGNORE_ENV": True,
            "LOGGING_ENABLED": logging_enabled,
            "AUDIT_ENABLED": audit_enabled,
            "DATABASE_URL": "sqlite:///:memory:",
        })()
        return Container(config)

    def test_auditing_can_be_off_while_logging_is_on(self):
        container = self._container(logging_enabled=True, audit_enabled=False)

        assert container.logger_component.logging_enabled is True
        assert container.audit_component.audit_enabled is False

    def test_logging_can_be_off_while_auditing_is_on(self):
        container = self._container(logging_enabled=False, audit_enabled=True)

        assert container.logger_component.logging_enabled is False
        assert container.audit_component.audit_enabled is True
