"""A journal line says which use case wrote it, not which module wired it.

Every application-layer logger is fetched by the DI container, under the
container's own ``__name__``, and the proxy stamped that name onto every
line as ``module`` -- which is the one field a journal record carries about
where it came from. Measured on the running stack: a refused journal read,
written from ``ReadJournalUseCase``, arrived as

    {"event": "Journal read refused", "required_permission": "audit:view",
     "logger": "link_shortener.infrastructure.di.container", ...}

so an operator filtering the journal by source was offered the wiring and
nothing else. Seventeen use cases shared that one name.

The name is now bound by ``BaseUseCase._get_logger`` from the class's own
``__module__``, which cannot be mistyped, and the proxy prefers a bound
name over the one it was built with. A name passed on a single call is
still ignored -- see ``test_failover_proxies``: where a line came from is a
property of its writer, and a line does not get to rename itself.
"""

from unittest.mock import Mock

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.journal_reader import (
    Journal, JournalPage,
)
from link_shortener.application.use_cases.journals.read_journal import (
    ReadJournalUseCase,
)
from link_shortener.infrastructure.logging.managers.logger_manager import (
    FailoverLoggerProxy, _ModuleLogger,
)


class Recording:
    """Stands in for the failover service, keeping what it was handed."""

    def __init__(self):
        self.calls = []

    def execute(self, method_name, message, **kwargs):
        self.calls.append((method_name, message, kwargs))


class RecordingLogger:
    """Stands in for a single implementation, keeping the same."""

    def __init__(self):
        self.calls = []

    def info(self, message, **kwargs):
        self.calls.append(("info", message, kwargs))


class TestABoundModuleWins:
    """Both shapes of logger, because a deployment may hand out either."""

    def test_the_failover_proxy_prefers_the_bound_name(self):
        service = Recording()
        proxy = FailoverLoggerProxy(service, "infrastructure.di.container")

        proxy.bind(module="application.use_cases.read_journal").info("read")

        _, _, kwargs = service.calls[0]
        assert kwargs["module"] == "application.use_cases.read_journal"

    def test_the_single_logger_prefers_the_bound_name(self):
        underlying = RecordingLogger()
        logger = _ModuleLogger(underlying, "infrastructure.di.container")

        logger.bind(module="application.use_cases.read_journal").info("read")

        _, _, kwargs = underlying.calls[0]
        assert kwargs["module"] == "application.use_cases.read_journal"


class TestAUseCaseNamesItself:

    @pytest.fixture
    def logger(self):
        """A logger that remembers what was bound to it."""
        bound = Mock()
        raw = Mock()
        raw.bind.return_value = bound
        raw.bound = bound
        return raw

    def test_the_module_bound_is_the_use_case_s_own(self, logger):
        uow = Mock()
        uow.__enter__ = Mock(return_value=uow)
        uow.__exit__ = Mock(return_value=False)
        uow.users.find_by_id.return_value = None
        authorization = Mock()
        authorization.is_allowed.return_value = True

        use_case = ReadJournalUseCase(
            reader=a_reader(),
            authorization_service=authorization,
            uow_factory=Mock(return_value=uow),
            logger=logger,
            audit_logger=Mock(),
        )
        use_case.execute(Journal.APPLICATION, a_context())

        bound_as = logger.bind.call_args.kwargs["module"]
        assert bound_as == ReadJournalUseCase.__module__
        assert "infrastructure" not in bound_as

    def test_the_name_is_taken_from_the_class_and_not_typed_out(self, logger):
        """A subclass says its own module, which a literal could not do.

        The point of reading ``type(self).__module__`` rather than writing
        the name down: a literal in the base class would name the base
        class for every use case in the application, which is the fault
        being fixed with a different wrong answer.
        """

        class Elsewhere(ReadJournalUseCase):
            pass

        Elsewhere.__module__ = "somewhere.else"
        uow = Mock()
        uow.__enter__ = Mock(return_value=uow)
        uow.__exit__ = Mock(return_value=False)
        uow.users.find_by_id.return_value = None
        authorization = Mock()
        authorization.is_allowed.return_value = True

        use_case = Elsewhere(
            reader=a_reader(),
            authorization_service=authorization,
            uow_factory=Mock(return_value=uow),
            logger=logger,
            audit_logger=Mock(),
        )
        use_case.execute(Journal.APPLICATION, a_context())

        assert logger.bind.call_args.kwargs["module"] == "somewhere.else"


def a_reader() -> Mock:
    """A reader answering with an empty page.

    A bare ``Mock`` will not do: ``execute`` counts the lines it got, and
    a mock has no length.

    Returns:
        The stubbed port.
    """
    port = Mock()
    port.tail.return_value = JournalPage(
        lines=(), total_scanned=0, reached_start=True,
        files_read=(), oldest_available=None,
    )
    return port


def a_context() -> RequestContext:
    """A signed-in-looking context; who it is does not matter here.

    Returns:
        The context.
    """
    return RequestContext(
        request_id="req-1",
        remote_addr="127.0.0.1",
        request_path="/api/v1/journals/application",
        request_method="GET",
        current_user=None,
    )
