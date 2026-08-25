"""Registration must not say whether an address is already registered.

The response is one half of that and the work behind it is the other. A
taken address returning before the password is hashed makes it 290x faster
than a free one -- so these tests hold the shape of the work, not just the
shape of the answer: both paths hash exactly once and
both hand exactly one message to the queue.

What they do not hold is equality of writing, because there is none: a
free address inserts two rows and commits, a taken one writes nothing.
That remainder is small beside a bcrypt hash, it did not show up in the
measurement, and it is written down in the developer guide rather than
pretended away here.

The unit of work is a stand-in with real behaviour rather than a mock:
what is under test is a sequence of decisions, and a mock agrees with
every sequence.
"""

from unittest.mock import Mock

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.mailer import MailDeliveryError
from link_shortener.application.use_cases.auth.register import RegisterUseCase
from link_shortener.application.use_cases.auth.send_account_exists_email import (
    SendAccountExistsEmailUseCase,
)
from link_shortener.domain import (
    Email, EmailAlreadyRegisteredError, PasswordHash, Role, User,
)


PASSWORD = "StrongPass1!"
HASH = "$2b$12$" + "x" * 53
TAKEN = "taken@example.com"
FREE = "free@example.com"


class FakeUsers:
    """An in-memory stand-in for the user repository."""

    def __init__(self, users=None):
        self.users = list(users or [])

    def find_by_email(self, email):
        return next((u for u in self.users if u.email.value == email.value), None)

    def save(self, user):
        if user not in self.users:
            self.users.append(user)
        return user


class FakeVerifications:
    """An in-memory stand-in for the confirmation repository."""

    def __init__(self):
        self.rows = []

    def save(self, verification):
        self.rows.append(verification)
        return verification


class FakeUow:
    """A unit of work whose repositories are the fakes above.

    Records the order of its own events, because the order is a rule here
    as much as on the other path: a message handed off inside the block is
    a network call made with the transaction still open.
    """

    def __init__(self, users=None):
        self.users = FakeUsers(users)
        self.email_verifications = FakeVerifications()
        self.roles = Mock()
        self.roles.get_by_name.return_value = Role(id="r", name="user")
        self.commits = 0
        self.events = []

    def commit(self):
        self.commits += 1
        self.events.append("commit")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *rest):
        self.events.append("closed")
        return False


def context():
    """A minimal request context."""
    return RequestContext(request_id="test")


def an_account(email=TAKEN):
    """An account that already holds an address."""
    return User.create(
        email=Email(email),
        password_hash=PasswordHash(HASH),
        roles=[Role(id="r", name="user")],
    )


@pytest.fixture
def uow():
    """A unit of work that already holds one registered address."""
    return FakeUow(users=[an_account()])


@pytest.fixture
def queue():
    """A task queue that accepts everything handed to it."""
    q = Mock()
    q.enqueue_verification_email.return_value = True
    q.enqueue_account_exists_email.return_value = True
    return q


@pytest.fixture
def auth():
    """An authentication service that hashes to a fixed value."""
    service = Mock()
    service.hash_password.return_value = HASH
    return service


@pytest.fixture
def register(uow, queue, auth):
    """Registration wired to the fakes above."""
    return RegisterUseCase(
        uow_factory=lambda read_only=False: uow,
        authentication_service=auth,
        logger=Mock(),
        default_role_name="user",
        task_queue=queue,
        verification_ttl_hours=24,
    )


class TestATakenAddressCostsWhatAFreeOneCosts:
    """The expensive work has to happen on both paths or on neither."""

    def test_the_password_is_hashed_for_a_taken_address(self, register, auth):
        """This is the one that closes the timing channel.

        Returning before the hash is what made a taken address answer in
        under a millisecond while a free one took ~162 ms. Any change that
        puts the existence check back in front of the hash fails here.
        """
        register.execute(TAKEN, PASSWORD, context())

        auth.hash_password.assert_called_once_with(PASSWORD)

    def test_one_message_is_handed_off_for_a_taken_address(
        self, register, queue
    ):
        """Without a broker the message goes out on the request thread, so
        a path that sent none would be shorter by an SMTP exchange."""
        register.execute(TAKEN, PASSWORD, context())

        queue.enqueue_account_exists_email.assert_called_once()
        assert queue.enqueue_account_exists_email.call_args.args[0] == TAKEN

    def test_a_free_address_also_hashes_once_and_mails_once(
        self, register, auth, queue
    ):
        """The same two things, in the same numbers, on the other path."""
        register.execute(FREE, PASSWORD, context())

        assert auth.hash_password.call_count == 1
        assert queue.enqueue_verification_email.call_count == 1
        assert queue.enqueue_account_exists_email.call_count == 0


class TestATakenAddressChangesNothing:
    """The notice is all that happens. Nothing is written, nothing leaks."""

    def test_no_second_account_is_created(self, register, uow):
        register.execute(TAKEN, PASSWORD, context())

        assert len(uow.users.users) == 1
        assert uow.commits == 0

    def test_no_confirmation_is_issued_for_somebody_elses_account(
        self, register, uow, queue
    ):
        """A confirmation link mailed here would be a working link to an
        account the caller does not own -- issued because they guessed the
        address."""
        register.execute(TAKEN, PASSWORD, context())

        assert uow.email_verifications.rows == []
        queue.enqueue_verification_email.assert_not_called()

    def test_the_notice_is_handed_off_after_the_block_is_closed(
        self, register, uow, queue
    ):
        """Order, not merely presence.

        Without a broker the hand-off *is* the SMTP exchange, on this
        thread. Made inside the ``with``, it holds a database connection
        open for the length of a network call -- the same rule the
        confirmation path keeps, and one this path broke when the notice
        was first added.
        """
        queue.enqueue_account_exists_email.side_effect = (
            lambda *a, **k: uow.events.append("enqueue") or True
        )

        register.execute(TAKEN, PASSWORD, context())

        assert uow.events == ["closed", "enqueue"], uow.events

    def test_neither_path_hands_anything_back(self, register):
        """An identifier returned here would answer the question the
        status code no longer answers."""
        taken = register.execute(TAKEN, PASSWORD, context())
        free = register.execute(FREE, PASSWORD, context())

        assert taken is None
        assert free is None

    def test_a_notice_that_cannot_be_sent_is_recorded_and_swallowed(
        self, uow, auth
    ):
        """The mail server must not become a way to tell the paths apart.

        A failed hand-off is worth a log line, and worth nothing else: it
        cannot change the status, the body, or whether an exception comes
        out, because all three are visible to the caller.
        """
        queue = Mock()
        queue.enqueue_account_exists_email.return_value = False
        logger = Mock()
        register = RegisterUseCase(
            uow_factory=lambda read_only=False: uow,
            authentication_service=auth,
            logger=logger,
            default_role_name="user",
            task_queue=queue,
            verification_ttl_hours=24,
        )

        assert register.execute(TAKEN, PASSWORD, context()) is None
        # The whole mock, not one method on it: a line written at another
        # level would slip past `logger.error.call_args`.
        assert any(
            "Account-exists notice was not handed off" in str(call)
            for call in logger.mock_calls
        )

    def test_the_attempt_is_recorded(self, register):
        """A run of these is somebody walking a list of addresses, and the
        response says nothing, so the log is the only place it shows.

        The address is in the log, and deliberately: the line written on
        every attempt (`"Registration attempt"`) carries it, as does the
        one for a successful registration. What the response withholds is
        withheld from the caller, not from the operator reading the logs.
        """
        logger = Mock()
        register.logger = logger

        register.execute(TAKEN, PASSWORD, context())

        assert any(
            "Registration attempt on a registered address" in str(call)
            for call in logger.mock_calls
        ), logger.mock_calls


class TestTheNoticeItself:
    """What the message may point at, and what it must not carry."""

    def _use_case(self, mailer, base_url="https://links.example.com"):
        templates = Mock()
        templates.account_exists_email.return_value = ("Subject", "body")
        return SendAccountExistsEmailUseCase(
            mailer=mailer,
            templates=templates,
            logger=Mock(),
            base_url=base_url,
        ), templates

    def test_the_link_is_built_from_the_configured_base(self):
        """Built from the Host header it would point wherever the caller
        said -- and the caller here is whoever typed somebody else's
        address into a registration form."""
        use_case, templates = self._use_case(Mock())

        use_case.execute("user@example.com", context())

        url = templates.account_exists_email.call_args.kwargs["sign_in_url"]
        assert url == "https://links.example.com/login"

    def test_a_trailing_slash_does_not_double(self):
        use_case, templates = self._use_case(
            Mock(), "https://links.example.com/"
        )

        use_case.execute("user@example.com", context())

        url = templates.account_exists_email.call_args.kwargs["sign_in_url"]
        assert "//login" not in url

    def test_a_delivery_failure_reaches_the_caller(self):
        """Swallowed here, a broker would count a lost message as sent and
        never retry it."""
        mailer = Mock()
        mailer.send.side_effect = MailDeliveryError("server down")
        use_case, _ = self._use_case(mailer)

        with pytest.raises(MailDeliveryError):
            use_case.execute("user@example.com", context())

    def test_it_is_sent_to_the_address_that_was_typed(self):
        mailer = Mock()
        use_case, _ = self._use_case(mailer)

        use_case.execute("user@example.com", context())

        assert mailer.send.call_args.kwargs["to"] == "user@example.com"


class TestTheAddressLosingARaceIsStillSilent:
    """
    The path taken when two registrations of one address overlap.

    ``_register`` reads first and writes after, so a second registration
    landing in between reaches the unique index and the repository raises.
    Registration catches that and answers exactly as it answers a taken
    address it saw coming -- 202, with the notice mailed to the address --
    because the alternative is a 500 on a public endpoint, and the
    difference between 202 and 500 says what the 202 is worded to
    withhold. Measured before that catch existed: five simultaneous
    registrations of one address answered 202, 500, 500 and two throttled.

    The catch recognises the clash as a ``ValidationError`` carrying
    ``field == "email"``. Nothing held that until this file did: making
    ``EmailAlreadyRegisteredError`` a class of its own -- an obvious
    tidying, since it has a code of its own -- left the whole suite green
    and the endpoint answering 500 in a race.
    """

    @pytest.fixture
    def racing_uow(self):
        """A unit of work that sees a free address and then loses it."""

        class LosesTheRace(FakeUow):
            def __init__(self):
                super().__init__(users=[])
                self.users.save = self._save_into_a_taken_address

            @staticmethod
            def _save_into_a_taken_address(user):
                raise EmailAlreadyRegisteredError()

        return LosesTheRace()

    @pytest.fixture
    def racing_register(self, racing_uow, queue, auth):
        return RegisterUseCase(
            uow_factory=lambda read_only=False, _u=racing_uow: _u,
            authentication_service=auth,
            logger=Mock(),
            default_role_name="user",
            task_queue=queue,
            verification_ttl_hours=24,
        )

    def test_the_race_is_not_raised_to_the_caller(self, racing_register):
        """A raised clash is a 500 on a public endpoint."""
        racing_register.execute(FREE, PASSWORD, context())

    def test_the_owner_of_the_address_is_notified(
        self, racing_register, queue
    ):
        """
        The same thing the seen-in-advance path does: the notice goes to
        the address, and no confirmation token is mailed to whoever
        typed it.
        """
        racing_register.execute(FREE, PASSWORD, context())

        queue.enqueue_account_exists_email.assert_called_once()
        queue.enqueue_verification_email.assert_not_called()
