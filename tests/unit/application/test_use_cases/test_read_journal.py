"""Who may read which journal, decided where the reading happens.

The route that will serve this carries a permission decorator, and the
decorator is not what these tests are about. A use case reached without one
-- from the CLI, from a task, from a route somebody adds next year -- must
refuse on its own, and it must refuse *before* the file is opened: a page
built from a refused read still had the journal in memory on the way to
deciding not to show it.

The second thing checked here is that the permission asked for is the one
belonging to the journal being read. Asking ``logs:view`` for all three
would pass every test that only ever looks at one journal, and would hand
the audit trail to every operator on the deployment.
"""

from unittest.mock import Mock

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.application.dtos.current_user_info import CurrentUserInfo
from link_shortener.application.ports.journal_reader import (
    Journal, JournalFilter, JournalLine, JournalPage,
)
from link_shortener.application.use_cases.journals.read_journal import (
    DEFAULT_LINES, PERMISSION_FOR, ReadJournalUseCase,
)
from link_shortener.domain import DomainError, SystemPermissions
from link_shortener.domain.entities.permission import Permission
from link_shortener.domain.entities.role import Role
from link_shortener.domain.entities.user import User
from link_shortener.infrastructure.auth.rbac_authorization_service import (
    RBACAuthorizationService,
)


def permission(name: str) -> Permission:
    """
    A permission entity from its name alone.

    Args:
        name: The ``resource:action`` string.

    Returns:
        The entity, with the two halves of the name split back out.
    """
    resource, action = name.split(":", 1)
    return Permission(id=f"p-{name}", name=name, resource=resource, action=action)


def user_holding(*names: str) -> User:
    """
    A user carrying exactly the named permissions, through one role.

    Args:
        names: Permission names the user's role grants.

    Returns:
        The user entity.
    """
    role = Role(
        id="r-1",
        name="under-test",
        permissions=tuple(permission(name) for name in names),
    )
    return User.create(
        email="reader@example.com",
        password_hash="not-checked-here",
        roles=[role],
    )


def a_page() -> JournalPage:
    """
    One line of something, so a successful read is distinguishable.

    Returns:
        A page holding a single parsed line.
    """
    return JournalPage(
        lines=(
            JournalLine(
                raw='{"event": "started"}',
                fields={"event": "started"},
                parsed=True,
                source="application.log",
            ),
        ),
        total_scanned=1,
        reached_start=True,
        files_read=("application.log",),
        oldest_available=None,
    )


@pytest.fixture
def reader():
    """The journal reader, which must not be reached on a refusal."""
    port = Mock()
    port.tail.return_value = a_page()
    return port


@pytest.fixture
def uow_factory():
    """
    A unit of work whose user repository answers with whoever is set on it.

    The use case re-reads the requester from the database rather than
    trusting the request context, so every test here has to say what the
    database holds -- which is the point: ``find_by_id`` and the context
    are set independently, and one test sets them to disagree.
    """
    uow = Mock()
    uow.__enter__ = Mock(return_value=uow)
    uow.__exit__ = Mock(return_value=False)
    uow.users.find_by_id.return_value = None

    factory = Mock(return_value=uow)
    factory.uow = uow
    return factory


@pytest.fixture
def use_case(reader, uow_factory):
    """The use case over the real authorization service.

    Real rather than mocked, because half of what is being checked is which
    permission is asked for -- and a mock that answers ``True`` to anything
    would pass whatever was asked.
    """
    return ReadJournalUseCase(
        reader=reader,
        authorization_service=RBACAuthorizationService(
            uow_factory=None, logger=Mock()
        ),
        uow_factory=uow_factory,
        logger=Mock(),
        audit_logger=Mock(),
    )


def context_of(user=None) -> RequestContext:
    """
    A request context, signed in or not.

    Args:
        user: The domain user the request is acting as, or ``None``.

    Returns:
        The context.
    """
    return RequestContext(
        request_id="req-1",
        remote_addr="127.0.0.1",
        request_path="/api/v1/journals/application",
        request_method="GET",
        current_user=(
            None if user is None
            else CurrentUserInfo(
                id=user.id,
                email=str(user.email),
                roles=["under-test"],
                is_active=True,
            )
        ),
    )


def signed_in_as(user, uow_factory) -> RequestContext:
    """
    Put a user behind both the context and the database read.

    Args:
        user: The domain user.
        uow_factory: The factory fixture, whose repository is set here.

    Returns:
        The matching request context.
    """
    uow_factory.uow.users.find_by_id.return_value = user
    return context_of(user)


class TestEachJournalIsReadUnderItsOwnPermission:
    """
    The whole reason there are two permissions.

    Each case reads one journal holding one permission, and the other
    journals are asked for in the same breath: a use case that asked
    ``logs:view`` for everything passes the first half of each of these and
    fails the second.
    """

    def test_the_operational_journals_open_to_logs_view(
        self, use_case, uow_factory, reader
    ):
        context = signed_in_as(
            user_holding(SystemPermissions.LOGS_VIEW.value), uow_factory
        )

        assert use_case.execute(Journal.APPLICATION, context).lines
        assert use_case.execute(Journal.ERROR, context).lines

        with pytest.raises(DomainError) as refused:
            use_case.execute(Journal.AUDIT, context)
        assert refused.value.code == "FORBIDDEN"

    def test_the_audit_journal_opens_to_audit_view(
        self, use_case, uow_factory
    ):
        context = signed_in_as(
            user_holding(SystemPermissions.AUDIT_VIEW.value), uow_factory
        )

        assert use_case.execute(Journal.AUDIT, context).lines

        for journal in (Journal.APPLICATION, Journal.ERROR):
            with pytest.raises(DomainError) as refused:
                use_case.execute(journal, context)
            assert refused.value.code == "FORBIDDEN", journal

    def test_the_administrative_bypass_stops_at_the_audit_journal(
        self, use_case, uow_factory
    ):
        """The limit of ``admin:all``, measured through this use case.

        ``BEYOND_ADMIN_ALL`` is tested where it is defined; what is checked
        here is that this use case asks the question in a way that reaches
        it. Asking ``logs:view`` for the audit journal -- one line, easy to
        write -- hands an administrator the record kept about them, and the
        service would answer ``True`` without hesitating.
        """
        context = signed_in_as(
            user_holding(SystemPermissions.ADMIN_ALL.value), uow_factory
        )

        assert use_case.execute(Journal.APPLICATION, context).lines

        with pytest.raises(DomainError) as refused:
            use_case.execute(Journal.AUDIT, context)
        assert refused.value.code == "FORBIDDEN"

    def test_every_journal_has_a_permission(self):
        """
        Completeness over the enum, checked rather than assumed.

        A fourth journal added to ``Journal`` with no entry in
        ``PERMISSION_FOR`` would raise ``KeyError`` at the first read --
        a 500 on a route, in production, on the journal somebody had just
        gone looking for.
        """
        assert set(PERMISSION_FOR) == set(Journal)
        assert set(PERMISSION_FOR.values()) <= set(SystemPermissions.all_values())


class TestARefusalDoesNotReadTheFile:

    def test_the_reader_is_never_reached_by_a_caller_without_the_permission(
        self, use_case, uow_factory, reader
    ):
        """
        Order matters, not just the outcome.

        Reading first and refusing afterwards gives the same status code
        and puts the journal in the process's memory on the way there --
        and, on the audit journal, costs the disk read the permission split
        exists to make somebody accountable for.
        """
        context = signed_in_as(
            user_holding(SystemPermissions.LOGS_VIEW.value), uow_factory
        )

        with pytest.raises(DomainError):
            use_case.execute(Journal.AUDIT, context)

        reader.tail.assert_not_called()

    def test_an_anonymous_caller_is_told_to_authenticate(
        self, use_case, reader
    ):
        """
        ``UNAUTHENTICATED``, not ``FORBIDDEN``: one answer for both leaves
        a client unable to tell "log in" from "logging in will not help".
        """
        with pytest.raises(DomainError) as refused:
            use_case.execute(Journal.APPLICATION, context_of(None))

        assert refused.value.code == "UNAUTHENTICATED"
        reader.tail.assert_not_called()

    def test_a_refusal_is_written_down(self, reader, uow_factory):
        """
        An attempt that was refused is what an operator goes looking for
        afterwards, and it is the only trace such an attempt leaves.
        """
        bound = Mock()
        logger = Mock()
        logger.bind.return_value = bound
        use_case = ReadJournalUseCase(
            reader=reader,
            authorization_service=RBACAuthorizationService(
                uow_factory=None, logger=Mock()
            ),
            uow_factory=uow_factory,
            logger=logger,
            audit_logger=Mock(),
        )
        context = signed_in_as(
            user_holding(SystemPermissions.LOGS_VIEW.value), uow_factory
        )

        with pytest.raises(DomainError):
            use_case.execute(Journal.AUDIT, context)

        bound.warning.assert_called_once()
        assert bound.warning.call_args.kwargs["required_permission"] == (
            SystemPermissions.AUDIT_VIEW.value
        )


class TestThePermissionsAreReadFromTheDatabase:
    """
    Not from the request context, which carries role *names* and was
    assembled when the request began.

    A role removed while a page was open must stop opening the journal on
    the next poll, and the page polls every few seconds -- so the window
    between "the grant was withdrawn" and "the reading stops" is exactly as
    long as this decision is stale.
    """

    def test_a_context_naming_a_role_the_account_no_longer_holds_is_refused(
        self, use_case, uow_factory, reader
    ):
        entitled = user_holding(SystemPermissions.AUDIT_VIEW.value)
        context = context_of(entitled)
        # The account as the database now has it: the role is gone.
        uow_factory.uow.users.find_by_id.return_value = user_holding(
            SystemPermissions.LINK_VIEW_OWN.value
        )

        with pytest.raises(DomainError) as refused:
            use_case.execute(Journal.AUDIT, context)

        assert refused.value.code == "FORBIDDEN"
        reader.tail.assert_not_called()

    def test_the_account_is_looked_up_by_the_id_the_context_carries(
        self, use_case, uow_factory
    ):
        reading = user_holding(SystemPermissions.LOGS_VIEW.value)
        context = signed_in_as(reading, uow_factory)

        use_case.execute(Journal.APPLICATION, context)

        uow_factory.uow.users.find_by_id.assert_called_once_with(reading.id)

    def test_the_read_is_taken_against_a_read_only_transaction(
        self, use_case, uow_factory
    ):
        """Nothing here writes, and the transaction says so."""
        context = signed_in_as(
            user_holding(SystemPermissions.LOGS_VIEW.value), uow_factory
        )

        use_case.execute(Journal.APPLICATION, context)

        uow_factory.assert_called_once_with(read_only=True)


class TestWhatTheCallerAskedForReachesTheReader:

    def test_the_defaults_are_two_hundred_lines_of_the_live_journal(
        self, use_case, uow_factory, reader
    ):
        context = signed_in_as(
            user_holding(SystemPermissions.LOGS_VIEW.value), uow_factory
        )

        use_case.execute(Journal.APPLICATION, context)

        reader.tail.assert_called_once_with(
            Journal.APPLICATION,
            limit=DEFAULT_LINES,
            include_archives=False,
            where=None,
        )

    def test_a_limit_and_the_archives_are_passed_through(
        self, use_case, uow_factory, reader
    ):
        """
        Unclamped on the way through, deliberately: the ceiling is
        ``HARD_LIMIT`` in the reader, which is where it belongs -- the
        number reaches it from a request whatever route it took, and a
        second ceiling here would be a second number to keep in step.
        """
        context = signed_in_as(
            user_holding(SystemPermissions.LOGS_VIEW.value), uow_factory
        )

        use_case.execute(
            Journal.ERROR, context, limit=10_000, include_archives=True
        )

        reader.tail.assert_called_once_with(
            Journal.ERROR, limit=10_000, include_archives=True, where=None
        )

    def test_the_page_is_handed_back_as_the_reader_gave_it(
        self, use_case, uow_factory, reader
    ):
        page = a_page()
        reader.tail.return_value = page
        context = signed_in_as(
            user_holding(SystemPermissions.LOGS_VIEW.value), uow_factory
        )

        assert use_case.execute(Journal.APPLICATION, context) is page


class TestReadingAJournalLeavesARecord:
    """The trace that reading the journals used to leave, which was none.

    An account holding ``audit:view`` could read every destination address
    and every account that followed one, and nothing anywhere said it had
    happened. The gap was written down in ``docs/decisions.md`` as open;
    this is it being closed, and the interesting half is what is *not*
    recorded -- the page polls, so a record per read would put twelve lines
    a minute into the journal it is displaying.
    """

    @pytest.fixture
    def audit(self):
        """The audit logger, watched for what a read writes to it."""
        logger = Mock()
        logger.bind.return_value = logger
        return logger

    @pytest.fixture
    def use_case(self, reader, uow_factory, audit):
        """The use case over a watched audit logger."""
        return ReadJournalUseCase(
            reader=reader,
            authorization_service=RBACAuthorizationService(
                uow_factory=None, logger=Mock()
            ),
            uow_factory=uow_factory,
            logger=Mock(),
            audit_logger=audit,
        )

    @pytest.fixture
    def auditor(self, uow_factory):
        """A caller entitled to all three journals."""
        return signed_in_as(
            user_holding(
                SystemPermissions.AUDIT_VIEW.value,
                SystemPermissions.LOGS_VIEW.value,
            ),
            uow_factory,
        )

    def test_going_to_look_is_recorded(self, use_case, audit, auditor):
        use_case.execute(Journal.AUDIT, auditor)

        _, kwargs = audit.log_audit_viewed.call_args
        assert kwargs["journal"] == "audit"
        assert kwargs["reason"] == "opened"

    def test_each_journal_is_recorded_under_its_own_name(
        self, use_case, audit, auditor
    ):
        """"Somebody read a journal" does not say which one, and the three
        are not equally sensitive."""
        for journal in (Journal.APPLICATION, Journal.ERROR, Journal.AUDIT):
            use_case.execute(journal, auditor)

        written = [
            call.kwargs["journal"] for call in audit.log_audit_viewed.call_args_list
        ]
        assert written == ["application", "error", "audit"]

    def test_following_the_tail_is_not_recorded_again(
        self, use_case, audit, auditor
    ):
        """The page refreshing itself is the same reading, still going on.

        Recorded per poll, an open page writes twelve lines a minute into
        the journal it is showing -- each of which is then shown, pushing
        out the lines the reader came for.
        """
        use_case.execute(Journal.AUDIT, auditor, following=True)

        audit.log_audit_viewed.assert_not_called()

    def test_reaching_into_the_archives_is_recorded_when_asked_for(
        self, use_case, audit, auditor
    ):
        """Going further back is somebody going to look, and says so."""
        use_case.execute(Journal.AUDIT, auditor, include_archives=True)

        assert audit.log_audit_viewed.call_args.kwargs["reason"] == "archives"

    def test_polling_with_the_archives_on_is_not_recorded_again(
        self, use_case, audit, auditor
    ):
        """Turning the archives on was recorded; the timer after it is not.

        The page polls whatever is on screen, the archives included, so
        exempting the poll and then re-admitting it whenever the archives
        are on exempts nothing: the button is remembered across visits,
        and one open tab wrote a line every ten seconds.
        """
        use_case.execute(Journal.AUDIT, auditor, include_archives=True,
                         following=True)

        audit.log_audit_viewed.assert_not_called()

    def test_a_refused_read_is_not_recorded_as_a_read(
        self, use_case, audit, uow_factory
    ):
        """It did not happen. The refusal is written by the permission
        check, in its own line, as a warning."""
        context = signed_in_as(
            user_holding(SystemPermissions.LOGS_VIEW.value), uow_factory
        )

        with pytest.raises(DomainError):
            use_case.execute(Journal.AUDIT, context)

        audit.log_audit_viewed.assert_not_called()

    def test_the_record_carries_who_and_from_where(
        self, use_case, audit, auditor
    ):
        """A reading nobody can be attached to answers nothing."""
        use_case.execute(Journal.AUDIT, auditor)

        _, bound = audit.bind.call_args
        assert bound["user_id"] == auditor.current_user.id
        assert bound["remote_addr"] == "127.0.0.1"


class TestASearchIsRecordedWithWhatWasSearchedFor:
    """A reading and a search are different acts, and the terms say which.

    "Read the audit journal" and "read the audit journal for one account's
    failed logins" are not the same thing to find afterwards, so the terms
    go into the record. What they do not do is decide whether there is a
    record at all: that is the follow flag alone, because a request
    carrying terms says nothing about whether they were just typed or are
    being polled for the hundredth time.
    """

    @pytest.fixture
    def audit(self):
        """The audit logger, watched for what a search writes to it."""
        logger = Mock()
        logger.bind.return_value = logger
        return logger

    @pytest.fixture
    def use_case(self, reader, uow_factory, audit):
        return ReadJournalUseCase(
            reader=reader,
            authorization_service=RBACAuthorizationService(
                uow_factory=None, logger=Mock()
            ),
            uow_factory=uow_factory,
            logger=Mock(),
            audit_logger=audit,
        )

    @pytest.fixture
    def auditor(self, uow_factory):
        return signed_in_as(
            user_holding(SystemPermissions.AUDIT_VIEW.value), uow_factory
        )

    def test_the_terms_reach_the_record(self, use_case, audit, auditor):
        use_case.execute(
            Journal.AUDIT,
            auditor,
            where=JournalFilter(account="u-1", event_type="LOGIN_FAILED"),
        )

        _, kwargs = audit.log_audit_viewed.call_args
        assert kwargs["filters"] == {
            "account": "u-1", "event_type": "LOGIN_FAILED"
        }
        assert kwargs["reason"] == "searched"

    def test_terms_that_were_not_given_are_absent_rather_than_null(
        self, use_case, audit, auditor
    ):
        """A record of a search should say what was asked, not list what
        was not."""
        use_case.execute(
            Journal.AUDIT, auditor, where=JournalFilter(short_code="-gxXupR")
        )

        assert audit.log_audit_viewed.call_args[1]["filters"] == {
            "short_code": "-gxXupR"
        }

    def test_a_poll_carrying_the_same_terms_is_not_recorded_again(
        self, use_case, audit, auditor
    ):
        """Asking the question was recorded; the timer repeating it is not.

        Nothing in a request distinguishes new terms from the same terms
        polled again, so recording every poll that carries terms records
        the tail refreshing itself -- six lines a minute, in the journal
        on screen, and the search that put them there is displaced by
        them. The submit that set the terms reloads with ``follow=false``
        and is recorded there.
        """
        use_case.execute(
            Journal.AUDIT,
            auditor,
            following=True,
            where=JournalFilter(account="u-1"),
        )

        audit.log_audit_viewed.assert_not_called()

    def test_an_empty_filter_is_not_a_search(self, use_case, audit, auditor):
        """The viewer passes one always, so an empty filter must leave the
        polling exemption exactly as it was."""
        use_case.execute(
            Journal.AUDIT, auditor, following=True, where=JournalFilter()
        )

        audit.log_audit_viewed.assert_not_called()

    def test_the_terms_reach_the_reader(self, use_case, reader, auditor):
        """Recorded and applied are two different things, and only one of
        them answers the reader's question."""
        where = JournalFilter(remote_addr="10.0.0.1")

        use_case.execute(Journal.AUDIT, auditor, where=where)

        assert reader.tail.call_args.kwargs["where"] is where
