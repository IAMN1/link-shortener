"""Reading a journal on behalf of a caller entitled to read that one.

The reader in ``infrastructure/logging/journal_reader.py`` answers "what is
at the end of this file". This is the part that decides whether the caller
may be told, and it is a decision the reader deliberately does not make:
handed a ``Journal`` it reads it, which is what makes it usable by the CLI
and by a test without a request anywhere near.

Two permissions rather than one, because the three journals do not expose
the same thing. ``audit.log`` carries destination addresses and the accounts
that followed them; ``application.log`` and ``error.log`` carry the email
address of everyone who registered, signed in, or failed to sign in. Google
Cloud draws the line in the same place, between ``logging.viewer`` and
``logging.privateLogViewer``.
"""

from dataclasses import dataclass
from typing import Optional

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.auth.authorization_service import (
    AuthorizationService,
)
from link_shortener.application.ports.journal_reader import (
    Journal, JournalFilter, JournalPage, JournalReaderPort,
)
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.ports.uow import UnitOfWorkFactory
from link_shortener.application.use_cases.admin.privilege_guard import load_actor
from link_shortener.application.use_cases.base_use_case import BaseUseCase
from link_shortener.domain import DomainError, SystemPermissions
from link_shortener.domain.i18n import N_


PERMISSION_FOR = {
    Journal.AUDIT: SystemPermissions.AUDIT_VIEW.value,
    Journal.APPLICATION: SystemPermissions.LOGS_VIEW.value,
    Journal.ERROR: SystemPermissions.LOGS_VIEW.value,
}
"""Which permission each journal is read under.

A mapping rather than a branch, and complete over the enum rather than
falling back to a default: a journal added to ``Journal`` with no entry here
raises ``KeyError`` at the first read instead of quietly inheriting whatever
the last ``else`` happened to grant. ``tests`` check the two sides against
each other, so the failure is at build time rather than in production.
"""

DEFAULT_LINES = 200
"""Lines a caller gets who asked for no particular number.

Two hundred is what the measurement in the reader was taken at -- 5.2 ms and
constant memory on a gigabyte -- and roughly a screen and a half of a
journal that is being read from the end because something just happened.
"""


@dataclass
class ReadJournalUseCase(BaseUseCase):
    """
    Read the end of one journal, if the caller is entitled to that journal.

    The permission is checked here as well as on the route, and that is not
    belt-and-braces for its own sake: the route's decorator guards the HTTP
    surface, while this guards the use case, which the CLI and any later
    caller reach without passing a decorator. The check that matters is the
    one nearest the data.

    The requester is re-read from the database rather than taken from the
    request context, for the reason the administrative use cases do it: the
    context carries role *names*, assembled when the request began, and a
    permission decision needs permissions as they are now. A role removed a
    moment ago must not still open the audit journal.

    Attributes:
        reader: Port that reads the journals off wherever they are written.
        authorization_service: Service that answers permission questions.
        uow_factory: Callable that returns a new Unit of Work instance.
        logger: Application logger.
        audit_logger: Audit logger, where a read that was not a
            continuation of an earlier one is recorded.
    """

    reader: JournalReaderPort
    authorization_service: AuthorizationService
    uow_factory: UnitOfWorkFactory
    logger: Logger
    audit_logger: AuditLogger

    def execute(
        self,
        journal: Journal,
        context: RequestContext,
        limit: int = DEFAULT_LINES,
        include_archives: bool = False,
        following: bool = False,
        where: Optional[JournalFilter] = None,
    ) -> JournalPage:
        """
        Read the most recent lines of a journal.

        Args:
            journal: Which journal to read. A member of the enum, so a
                string arriving from a request cannot become a path -- the
                web layer converts, and an unknown name is refused there.
            context: Request context carrying the caller's identity.
            limit: Most lines to return. Capped again by the reader, which
                is where the ceiling belongs: the number reaches it from a
                request whatever route it took to get there.
            include_archives: Whether to continue into the rotated files
                once the live journal is exhausted.
            following: Whether this read continues one already recorded --
                the page polling the tail it is displaying. It decides
                whether the read leaves a record, and only that; what is
                read and who may read it are the same either way.
            where: What the caller is looking for, or ``None`` for the
                plain tail. A search is recorded even when it says it is
                following: the tail refreshing itself is the same reading
                going on, while a new set of terms is somebody asking a
                new question.

        Returns:
            The page, oldest line first.

        Raises:
            DomainError: ``UNAUTHENTICATED`` when nobody is signed in,
                ``FORBIDDEN`` when the caller holds the wrong permission
                for this journal.
        """
        log = self._get_logger(self.logger, context, journal=journal.value)

        self._require_may_read(journal, context, log)

        page = self.reader.tail(
            journal,
            limit=limit,
            include_archives=include_archives,
            where=where,
        )

        self._record_the_read(
            journal, context, include_archives, following, where
        )

        # `debug`, not `info`: this runs on every poll of an open page, and
        # a page refreshing every five seconds would otherwise write twelve
        # lines a minute into the journal it is displaying -- each of which
        # is then displayed, which is a service logging its own reflection.
        log.debug(
            "Journal read",
            lines=len(page.lines),
            files_read=list(page.files_read),
        )

        return page

    def _record_the_read(
        self,
        journal: Journal,
        context: RequestContext,
        include_archives: bool,
        following: bool,
        where: Optional[JournalFilter] = None,
    ) -> None:
        """
        Leave a record of this read, unless it merely continues one.

        Reading the journals used to leave no trace at all, which is the
        one thing the journals are for: an account granted ``audit:view``
        could read every destination address and every account that
        followed one, and nothing anywhere would say it had happened.

        Not every read, though, and the reason is the shape of this page
        rather than squeamishness about volume. The viewer polls, so a
        record per read would put twelve lines a minute into the journal
        being displayed -- each of which is then displayed, pushing out the
        lines the reader came for. What is recorded is the act of going to
        look: opening the page, switching to another journal, reaching back
        into the archives. What is not is the tail refreshing itself, which
        the caller marks by asking to follow.

        A caller marking a first read as a continuation therefore leaves no
        record. That is the price of deciding from the request alone rather
        than keeping per-reader state, and it is bounded: the permission
        itself is granted separately and its granting is recorded, so a
        reader can hide a reading but not the entitlement that allowed it.
        Written down in ``docs/decisions.md`` rather than left here.

        Args:
            journal: The journal that was just read.
            context: Request context carrying the caller's identity.
            include_archives: Whether the read reached into the archives.
            following: Whether the caller says this continues a read
                already recorded.
            where: What the caller searched for, if anything.
        """
        searching = bool(where and not where.is_empty)

        # Reaching into the archives is a deliberate act whichever way the
        # read is marked -- the page polls its tail, it does not poll the
        # rotated files behind it -- and so is naming what to look for.
        if following and not (include_archives or searching):
            return

        audit = self._get_audit_logger(self.audit_logger, context)
        audit.log_audit_viewed(
            journal=journal.value,
            reason=self._why_this_read_is_recorded(searching, include_archives),
            filters=self._terms_of(where),
        )

    @staticmethod
    def _why_this_read_is_recorded(searching: bool, archives: bool) -> str:
        """Name what made this read worth a record.

        Args:
            searching: Whether terms were given.
            archives: Whether the read reached into the archives.

        Returns:
            The reason, which a later search over the audit journal itself
            can be filtered by.
        """
        if searching:
            return "searched"
        return "archives" if archives else "opened"

    @staticmethod
    def _terms_of(where: Optional[JournalFilter]) -> dict:
        """What was searched for, as it goes into the record.

        The terms are written down because what somebody went looking for
        is the part of a reading worth keeping: "read the audit journal"
        and "read the audit journal for one account's failed logins" are
        different acts. Empty fields are dropped rather than written as
        nulls -- a record of a search should say what was asked, not list
        what was not.

        Args:
            where: The filter, or ``None``.

        Returns:
            The terms that were set, as a mapping.
        """
        if where is None:
            return {}
        return {
            name: value
            for name, value in (
                ("event_type", where.event_type),
                ("account", where.account),
                ("remote_addr", where.remote_addr),
                ("short_code", where.short_code),
                ("since", where.since),
                ("until", where.until),
            )
            if value
        }

    def _require_may_read(
        self, journal: Journal, context: RequestContext, log: Logger
    ) -> None:
        """
        Check that this caller may read this journal.

        Args:
            journal: The journal about to be read.
            context: Request context carrying the caller's identity.
            log: Bound logger.

        Raises:
            DomainError: If the caller may not read it.
        """
        required = PERMISSION_FOR[journal]

        with self.uow_factory(read_only=True) as uow:
            requester = load_actor(context, uow)

        if self.authorization_service.is_allowed(requester, required):
            return

        # Asked after the permission check rather than before, the way the
        # route decorator does it: what the caller is missing decides which
        # refusal is truthful, and "log in" is the wrong advice for somebody
        # already logged in as the wrong person.
        if requester is None:
            raise DomainError(N_("Authentication required"), code="UNAUTHENTICATED")

        # A refusal here is worth a line in its own right. The permissions
        # were split so that reading the audit journal is a deliberate,
        # separately granted act; an attempt that was refused is exactly the
        # thing an operator wants to find afterwards.
        log.warning("Journal read refused", required_permission=required)
        raise DomainError(N_("Not authorized"), code="FORBIDDEN")
