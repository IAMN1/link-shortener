"""What the health probe answers on the logging this application sets up.

The failover service asks ``is_healthy()`` and now hands the work down on a
``False``. Every test that had ever asked the question attached a handler
directly to the logger under test -- a wiring this application does not use.
``setup_logging`` puts the handlers on the root logger and lets named loggers
propagate to it, so ``logger.handlers`` is empty for everything
``LoggerManager`` builds, and a probe reading that alone answered ``False``
for a logger whose records were arriving.

The consequence was not hypothetical: with ``LOGGER_TYPE=standard`` the
background check would take the work off the operator's chosen logger one
interval after start-up and never give it back, because the same probe would
go on answering ``False``.
"""

import logging

import pytest

from link_shortener.infrastructure.logging.bootstrap import setup_logging
from link_shortener.infrastructure.logging.handlers.raising import (
    OWN_LOGGER_NAMES,
)
from link_shortener.infrastructure.logging.managers.audit_manager import (
    AuditManager,
)
from link_shortener.infrastructure.logging.handlers.audit.standard import (
    StandardAuditLogger,
)
from link_shortener.infrastructure.logging.handlers.audit.structlog import (
    StructlogAuditLogger,
)
from link_shortener.infrastructure.logging.handlers.logger.standard import (
    StandardLogger,
)
from link_shortener.infrastructure.logging.handlers.logger.structlog import (
    StructLogger,
)
from link_shortener.infrastructure.logging.logging_settings import (
    LoggingSettings,
)
from link_shortener.infrastructure.logging.managers.logger_manager import (
    LoggerManager,
)


@pytest.fixture
def configured_logging(tmp_path):
    """
    Configure logging the way ``create_app`` does, into a temporary directory.

    Args:
        tmp_path: Directory for the log files, per test.

    Yields:
        A callable taking a logger type and configuring logging for it.
    """
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level

    def configure(logger_type: str = "auto"):
        settings = LoggingSettings(
            log_dir=str(tmp_path),
            log_file_name="link_shortener",
            audit_log_filename="audit",
            error_log_filename="error",
            log_date_format="%Y-%m-%d %H:%M:%S",
            log_to_console=False,
            log_to_file=True,
            log_level_str="INFO",
            debug=False,
            sqlalchemy_log_level="WARNING",
            werkzeug_log_level="WARNING",
            logger_type=logger_type,
            audit_enabled=True,
        )
        setup_logging(settings, logging_enabled=True, audit_enabled=True)

    yield configure

    root.handlers = saved_handlers
    root.setLevel(saved_level)


class TestHealthOnTheRealWiring:

    def test_the_named_logger_owns_no_handlers(self, configured_logging):
        # The premise of everything below, asserted rather than assumed: if
        # this ever changes the tests after it stop being about anything.
        configured_logging()

        assert logging.getLogger("global").handlers == []

    @pytest.mark.parametrize("logger_type", ["auto", "standard", "structlog"])
    def test_both_implementations_report_themselves_well(
        self, configured_logging, logger_type
    ):
        configured_logging(logger_type)

        assert StandardLogger(name="global").is_healthy() is True
        assert StructLogger(name="global").is_healthy() is True

    def test_both_audit_implementations_report_themselves_well(
        self, configured_logging
    ):
        configured_logging()

        assert StandardAuditLogger(name="audit").is_healthy() is True
        assert StructlogAuditLogger().is_healthy() is True

    def test_every_implementation_writes_under_a_name_of_this_application(
        self, configured_logging
    ):
        """The name decides whether a failed write is heard at all.

        ``_RaisesForOwnRecords`` lets an ``OSError`` out of a write only
        for records whose logger belongs to this application
        (``OWN_LOGGER_NAMES``); everything else keeps the standard
        library's behaviour, which is to swallow the failure in
        ``handleError``. So an implementation built under any other name --
        ``StructLogger(name="structlog")``, ``StandardAuditLogger(
        name="standard_audit")`` -- goes on being asked for records that
        quietly go nowhere: no exception, no demotion, ``dropped_calls``
        at zero, ``/api/v1/admin/health`` reporting the chain as active.
        Measured: each of those two renamings left the whole suite green,
        and the audit trail moved from ``audit.log`` into the application
        log with it.

        Read off the implementations the managers actually build, not off
        constructors called here: the renaming that survives is one made
        inside a manager.
        """
        configured_logging("auto")
        written = []

        class Catcher(logging.Handler):
            """Remembers the logger name of every record that arrives."""

            def emit(self, record):
                written.append(record.name)

        catcher = Catcher()
        # Both, because the audit tree does not propagate to the root.
        root = logging.getLogger()
        audit_tree = logging.getLogger("audit")
        root.addHandler(catcher)
        audit_tree.addHandler(catcher)
        try:
            loggers = LoggerManager(
                logger_type="auto", failover_check_interval=None
            )
            for implementation, _name in loggers._failover_service._services:
                implementation.info("probe")

            audits = AuditManager(
                audit_type="auto", failover_check_interval=None
            )
            for implementation, _name in audits._failover_service._services:
                implementation.log_url_created("abc123", "https://example.com")
        finally:
            root.removeHandler(catcher)
            audit_tree.removeHandler(catcher)

        assert len(written) == 4, (
            f"four implementations, {len(written)} records: {written}"
        )
        assert [
            name for name in written
            if name.split(".")[0] not in OWN_LOGGER_NAMES
        ] == []

    @pytest.mark.parametrize("logger_type", ["auto", "standard"])
    def test_a_check_leaves_the_work_where_the_operator_put_it(
        self, configured_logging, logger_type
    ):
        # The whole round, on the chain the manager actually builds. A probe
        # that answers False for a working logger shows up here as the work
        # moving on the first check after start-up.
        configured_logging(logger_type)
        manager = LoggerManager(logger_type=logger_type, failover_check_interval=None)
        failover = manager._failover_service
        assert failover is not None, "the chain was not built"
        chosen = failover.get_current_service_name()

        failover._run_check()
        failover._run_check()

        assert failover.get_current_service_name() == chosen
