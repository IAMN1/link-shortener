from dataclasses import dataclass

from link_shortener.application import (
    AuthorizationService, Journal, JournalReaderPort, Logger,
    ReadJournalUseCase, UnitOfWorkFactory,
)
from link_shortener.infrastructure.logging.journal_reader import FileJournalReader


@dataclass
class JournalUseCasesComponent:
    """
    Provides the use case that reads the journals back.

    The reader is built here rather than taken as an argument, because what
    it needs -- a directory and three file names -- is configuration, and
    the container is where configuration is turned into objects. The port
    stays the seam: a deployment that keeps its journals somewhere other
    than a local file changes this component and nothing else.

    Attributes:
        log_dir: Directory the journals are written to.
        log_filename: Base name of the application journal, without ``.log``.
        audit_log_filename: Base name of the audit journal.
        error_log_filename: Base name of the error journal.
        authorization_service: Service that answers permission questions.
        uow_factory: Callable that returns a new Unit of Work instance.
        logger: Application logger injected into the use case.
    """

    log_dir: str
    log_filename: str
    audit_log_filename: str
    error_log_filename: str
    authorization_service: AuthorizationService
    uow_factory: UnitOfWorkFactory
    logger: Logger

    def get_journal_reader(self) -> JournalReaderPort:
        """
        Return a reader wired to this deployment's journal file names.

        Returns:
            A ``FileJournalReader`` over the configured directory.
        """
        return FileJournalReader(
            log_dir=self.log_dir,
            file_names={
                Journal.APPLICATION: self.log_filename,
                Journal.AUDIT: self.audit_log_filename,
                Journal.ERROR: self.error_log_filename,
            },
        )

    def get_read_journal_use_case(self) -> ReadJournalUseCase:
        """
        Return a fully configured ``ReadJournalUseCase``.

        Returns:
            A new use case with the reader, the authorization service and
            the unit of work factory wired in.
        """
        return ReadJournalUseCase(
            reader=self.get_journal_reader(),
            authorization_service=self.authorization_service,
            uow_factory=self.uow_factory,
            logger=self.logger,
        )
