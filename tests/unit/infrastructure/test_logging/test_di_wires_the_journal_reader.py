"""The seam between the configured file names and the journal being read.

The reader is told which file each ``Journal`` member lives in, and the
container is the only place that mapping is built. Getting it wrong is
quiet: every file name defaults to the member's own name, so on an ordinary
deployment a mapping with two entries swapped reads exactly right until
somebody sets ``AUDIT_LOG_FILENAME``.

Swapping ``audit`` and ``error`` is not a cosmetic fault. ``Journal.ERROR``
is read under ``logs:view``, which every operator holds, and
``Journal.AUDIT`` under ``audit:view``, which is granted deliberately and
withheld from ``admin:all`` -- so the swap serves the audit journal to
whoever asks for the error one, and the permission split that the previous
branch was for stops meaning anything.

Asked with three names nobody would confuse for each other, because with the
defaults in place every wrong mapping still points at a real file.
"""

import pytest

from link_shortener.application.ports.journal_reader import Journal
from link_shortener.application.use_cases.journals.read_journal import (
    ReadJournalUseCase,
)


@pytest.fixture
def container(tmp_path):
    """
    A container over a configuration detached from the machine.

    Args:
        tmp_path: Directory standing in for the deployment's ``LOG_DIR``.

    Returns:
        The container.
    """
    from link_shortener.infrastructure.configs.app.testing import TestingConfig
    from link_shortener.infrastructure.di.container import Container

    config = type("DetachedConfig", (TestingConfig,), {
        # The fields read the environment otherwise, and this test would
        # then measure the machine it runs on.
        "IGNORE_ENV": True,
        "DATABASE_URL": "sqlite:///:memory:",
        "LOG_DIR": str(tmp_path),
        "LOG_FILENAME": "written-by-the-application",
        "AUDIT_LOG_FILENAME": "the-record-of-what-was-done",
        "ERROR_LOG_FILENAME": "what-went-wrong",
    })()
    return Container(config)


class TestTheContainerBuildsTheUseCase:

    def test_it_hands_out_a_use_case_with_every_collaborator_wired(
        self, container
    ):
        use_case = container.get_read_journal_use_case()

        assert isinstance(use_case, ReadJournalUseCase)
        assert use_case.reader is not None
        assert use_case.authorization_service is not None
        assert use_case.uow_factory is not None

    def test_the_component_is_built_once_and_kept(self, container):
        container.get_read_journal_use_case()
        first = container._journal_use_cases

        container.get_read_journal_use_case()

        assert container._journal_use_cases is first


class TestEachJournalPointsAtItsOwnConfiguredFile:

    @pytest.mark.parametrize("journal, configured", [
        pytest.param(Journal.APPLICATION, "written-by-the-application", id="application"),
        pytest.param(Journal.AUDIT, "the-record-of-what-was-done", id="audit"),
        pytest.param(Journal.ERROR, "what-went-wrong", id="error"),
    ])
    def test_the_name_the_operator_set_is_the_file_that_is_read(
        self, container, tmp_path, journal, configured
    ):
        """
        Args:
            journal: The member being resolved.
            configured: The base name that member must resolve to.
        """
        reader = container.get_read_journal_use_case().reader

        assert reader._path_of(journal) == tmp_path / f"{configured}.log"

    def test_the_directory_is_the_one_the_deployment_writes_to(
        self, container, tmp_path
    ):
        reader = container.get_read_journal_use_case().reader

        assert reader.log_dir == tmp_path
