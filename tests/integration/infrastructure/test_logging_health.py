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
