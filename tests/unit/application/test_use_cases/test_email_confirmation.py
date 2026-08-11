"""What registration, confirmation and resending do, one layer above the
database.

The unit of work is a stand-in with real behaviour rather than a mock that
answers whatever it is told: what is being tested here is a sequence --
issue, hand off, spend -- and a mock would agree with any sequence at all.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from link_shortener.application.context import RequestContext
from link_shortener.application.ports.mailer import MailDeliveryError
from link_shortener.application.use_cases.admin.users.clean_unverified_accounts import (
    CleanUnverifiedAccountsUseCase,
)
from link_shortener.application.use_cases.auth.register import RegisterUseCase
from link_shortener.application.use_cases.auth.resend_verification import (
    ResendVerificationUseCase,
)
from link_shortener.application.use_cases.auth.send_verification_email import (
    SendVerificationEmailUseCase,
)
from link_shortener.application.use_cases.auth.verify_email import VerifyEmailUseCase
from link_shortener.domain import (
    DomainError, Email, PasswordHash, Role, User, ValidationError
)
from link_shortener.domain.entities.email_verification import EmailVerification
from link_shortener.domain.value_objects.verification_token import (
    issue_token,
    token_digest,
)


PASSWORD = "StrongPass1!"
HASH = "$2b$12$" + "x" * 53


class FakeVerifications:
    """An in-memory stand-in for the confirmation repository."""

    def __init__(self):
        self.rows = []

    def save(self, verification):
        self.rows.append(verification)
        return verification

    def claim(self, token_hash):
        now = datetime.now(timezone.utc)
        for row in self.rows:
            if row.token_hash == token_hash and row.is_usable(now):
                row.spend(now)
                return row.user_id
        return None

    def find_by_token_hash(self, token_hash):
        return next((r for r in self.rows if r.token_hash == token_hash), None)

    def invalidate_for_user(self, user_id):
        spent = 0
        for row in self.rows:
            if row.user_id == user_id and row.used_at is None:
                row.spend()
                spent += 1
        return spent

    def delete_expired(self):
        now = datetime.now(timezone.utc)
        dead = [r for r in self.rows if not r.is_usable(now)]
        self.rows = [r for r in self.rows if r.is_usable(now)]
        return len(dead)


class FakeUsers:
    """An in-memory stand-in for the user repository."""

    def __init__(self, users=None):
        self.users = list(users or [])
        self.deleted_before = None

    def find_by_email(self, email):
        return next((u for u in self.users if u.email.value == email.value), None)

    def find_by_id(self, user_id):
        return next((u for u in self.users if u.id == user_id), None)

    def save(self, user):
        if user not in self.users:
            self.users.append(user)
        return user

    def delete_unverified_before(self, cutoff):
        self.deleted_before = cutoff
        doomed = [
            u for u in self.users
            if not u.email_verified and u.created_at < cutoff
        ]
        self.users = [u for u in self.users if u not in doomed]
        return len(doomed)


class FakeUow:
    """A unit of work whose repositories are the fakes above.

    Records the order of its own events, because the order is a rule: the
    message may only be handed off after the commit, or a worker can
    deliver a link to a row that is not there yet.

    Leaving an exception uncommitted is modelled too. The real
    ``SQLAlchemyUnitOfWork.__exit__`` rolls back on the way out, and a
    double that did not made a use case look like it kept a change it
    actually loses.
    """

    def __init__(self, users=None, roles=None):
        self.users = FakeUsers(users)
        self.email_verifications = FakeVerifications()
        self.roles = Mock()
        self.roles.get_by_name.return_value = (
            roles if roles is not None else Role(id="r", name="user")
        )
        self.commits = 0
        self.events = []
        self.rolled_back = 0

    def commit(self):
        self.commits += 1
        self.events.append("commit")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *rest):
        if exc_type is not None:
            self.rolled_back += 1
            self.events.append("rollback")
        return False


@pytest.fixture
def uow():
    """One unit of work, shared by the factory below across calls."""
    return FakeUow()


@pytest.fixture
def uow_factory(uow):
    """A factory handing back that same unit of work."""
    @contextmanager
    def factory(read_only=False):
        yield uow

    return lambda read_only=False: uow


def context():
    """A minimal request context."""
    return RequestContext(request_id="test")


class TestRegistration:
    """What an account looks like the moment it is created."""

    @pytest.fixture
    def register(self, uow_factory):
        """A registration use case with a queue that always accepts."""
        auth = Mock()
        auth.hash_password.return_value = HASH
        queue = Mock()
        queue.enqueue_verification_email.return_value = True
        use_case = RegisterUseCase(
            uow_factory=uow_factory,
            authentication_service=auth,
            logger=Mock(),
            default_role_name="user",
            task_queue=queue,
            verification_ttl_hours=24,
        )
        return use_case, queue

    def test_the_account_starts_unconfirmed(self, register, uow):
        use_case, _ = register

        use_case.execute("new@example.com", PASSWORD, context())

        assert uow.users.users[0].email_verified is False

    def test_a_confirmation_is_issued(self, register, uow):
        use_case, _ = register

        use_case.execute("new@example.com", PASSWORD, context())

        assert len(uow.email_verifications.rows) == 1
        assert uow.email_verifications.rows[0].user_id == uow.users.users[0].id

    def test_only_the_digest_is_stored(self, register, uow):
        """The row must not be usable as the link it stands for."""
        use_case, queue = register

        use_case.execute("new@example.com", PASSWORD, context())

        _, token, _ = queue.enqueue_verification_email.call_args.args
        stored = uow.email_verifications.rows[0].token_hash
        assert stored != token
        assert stored == token_digest(token)

    def test_the_message_is_handed_off_with_the_address(self, register):
        use_case, queue = register

        use_case.execute("new@example.com", PASSWORD, context())

        email, token, _ = queue.enqueue_verification_email.call_args.args
        assert email == "new@example.com"
        assert token

    def test_one_transaction_holds_the_account_and_the_token(
        self, register, uow
    ):
        """Committed separately, a crash between them leaves an account
        nobody can confirm and nobody can register again.

        Named for what it measures. As
        ``test_the_token_is_issued_before_the_commit`` it promised an
        ordering it never checked: moving the commit ahead of the token
        left this green.
        """
        use_case, _ = register

        use_case.execute("new@example.com", PASSWORD, context())

        assert uow.commits == 1

    def test_the_message_is_handed_off_after_the_commit(self, register, uow):
        """Order, not merely count.

        Published from inside the transaction, a worker can pick the task
        up and deliver the link before the row exists -- the recipient
        follows a working link and is told it is invalid -- and a commit
        that then fails leaves a live link for an account that never
        existed. It also holds a writing transaction open across a network
        call.
        """
        use_case, queue = register
        queue.enqueue_verification_email.side_effect = (
            lambda *a, **k: uow.events.append("enqueue") or True
        )

        use_case.execute("new@example.com", PASSWORD, context())

        assert uow.events == ["commit", "enqueue"], uow.events

    def test_a_message_that_cannot_be_sent_does_not_undo_the_account(
        self, uow_factory, uow
    ):
        """The mail server must not be able to stop registration.

        The account and its token are stored either way, so the person can
        ask for the message again -- and an anonymous caller learns
        nothing about whether the mail channel is up.
        """
        auth = Mock()
        auth.hash_password.return_value = HASH
        queue = Mock()
        queue.enqueue_verification_email.return_value = False
        use_case = RegisterUseCase(
            uow_factory=uow_factory,
            authentication_service=auth,
            logger=Mock(),
            default_role_name="user",
            task_queue=queue,
            verification_ttl_hours=24,
        )

        use_case.execute("new@example.com", PASSWORD, context())

        assert len(uow.users.users) == 1
        assert len(uow.email_verifications.rows) == 1

    def test_a_failed_handoff_is_recorded(self, uow_factory):
        """Nobody finds out from the response, so the log has to say it."""
        auth = Mock()
        auth.hash_password.return_value = HASH
        queue = Mock()
        queue.enqueue_verification_email.return_value = False
        logger = Mock()
        logger.bind.return_value = logger

        RegisterUseCase(
            uow_factory=uow_factory,
            authentication_service=auth,
            logger=logger,
            default_role_name="user",
            task_queue=queue,
            verification_ttl_hours=24,
        ).execute("new@example.com", PASSWORD, context())

        assert logger.error.called

    def test_the_token_never_reaches_the_log(self, uow_factory):
        auth = Mock()
        auth.hash_password.return_value = HASH
        queue = Mock()
        queue.enqueue_verification_email.return_value = True
        logger = Mock()
        logger.bind.return_value = logger

        RegisterUseCase(
            uow_factory=uow_factory,
            authentication_service=auth,
            logger=logger,
            default_role_name="user",
            task_queue=queue,
            verification_ttl_hours=24,
        ).execute("new@example.com", PASSWORD, context())

        _, token, _ = queue.enqueue_verification_email.call_args.args
        assert token not in str(logger.mock_calls)


class TestConfirmation:
    """Spending a token, and every way it fails alike."""

    @pytest.fixture
    def confirmed(self, uow_factory, uow):
        """A use case, plus an account with one live confirmation."""
        user = User.create(Email("who@example.com"), PasswordHash(HASH))
        uow.users.save(user)
        token = issue_token()
        uow.email_verifications.save(
            EmailVerification.issue(
                user_id=user.id, token_hash=token_digest(token), ttl_hours=24
            )
        )
        use_case = VerifyEmailUseCase(uow_factory=uow_factory, logger=Mock())
        return use_case, user, token

    def test_a_live_token_confirms_the_account(self, confirmed):
        use_case, user, token = confirmed

        use_case.execute(token, context())

        assert user.email_verified is True

    def test_a_token_works_once(self, confirmed):
        use_case, _, token = confirmed
        use_case.execute(token, context())

        with pytest.raises(ValidationError):
            use_case.execute(token, context())

    def test_an_unknown_token_is_refused(self, confirmed):
        use_case, _, _ = confirmed

        with pytest.raises(ValidationError):
            use_case.execute("never-issued", context())

    def test_an_expired_token_is_refused(self, uow_factory, uow):
        user = User.create(Email("late@example.com"), PasswordHash(HASH))
        uow.users.save(user)
        token = issue_token()
        uow.email_verifications.save(
            EmailVerification.issue(
                user_id=user.id,
                token_hash=token_digest(token),
                ttl_hours=1,
                now=datetime.now(timezone.utc) - timedelta(days=2),
            )
        )
        use_case = VerifyEmailUseCase(uow_factory=uow_factory, logger=Mock())

        with pytest.raises(ValidationError):
            use_case.execute(token, context())

        assert user.email_verified is False

    def test_a_token_naming_a_deleted_account_is_refused(self, uow_factory, uow):
        """The sweep can take the account while its link is in a mailbox."""
        token = issue_token()
        uow.email_verifications.save(
            EmailVerification.issue(
                user_id="gone", token_hash=token_digest(token), ttl_hours=24
            )
        )
        use_case = VerifyEmailUseCase(uow_factory=uow_factory, logger=Mock())

        with pytest.raises(ValidationError):
            use_case.execute(token, context())

    def test_every_refusal_says_the_same_thing(self, confirmed, uow_factory, uow):
        """Told apart, this route says who is registered.

        "Already used" says an account exists and someone confirmed it;
        "expired" says one existed recently, and "that account is gone"
        says one was swept. One sentence for all of them.

        The swept-account branch is in the list because it was the one not
        in it: a separate message there passed every other test here, and
        it is the branch a stranger reaches by holding on to a link.
        """
        use_case, _, token = confirmed
        use_case.execute(token, context())

        orphaned = issue_token()
        uow.email_verifications.save(
            EmailVerification.issue(
                user_id="account-that-was-swept",
                token_hash=token_digest(orphaned),
                ttl_hours=24,
            )
        )

        expired = issue_token()
        uow.email_verifications.save(
            EmailVerification.issue(
                user_id="whoever",
                token_hash=token_digest(expired),
                ttl_hours=1,
                now=datetime.now(timezone.utc) - timedelta(days=2),
            )
        )

        messages = set()
        for bad in [token, "never-issued", "", orphaned, expired]:
            with pytest.raises(ValidationError) as raised:
                use_case.execute(bad, context())
            messages.add(str(raised.value))

        assert len(messages) == 1, messages


class TestResending:
    """A new confirmation, and the ones it retires."""

    def _use_case(self, uow_factory, queue):
        return ResendVerificationUseCase(
            uow_factory=uow_factory,
            task_queue=queue,
            logger=Mock(),
            ttl_hours=24,
        )

    def test_an_unconfirmed_account_gets_a_new_message(self, uow_factory, uow):
        uow.users.save(User.create(Email("wait@example.com"), PasswordHash(HASH)))
        queue = Mock()
        queue.enqueue_verification_email.return_value = True

        self._use_case(uow_factory, queue).execute("wait@example.com", context())

        assert queue.enqueue_verification_email.called

    def test_the_older_link_stops_working(self, uow_factory, uow):
        """Two live links mean an address confirmed by whichever is
        opened -- including one a stranger asked for an hour ago."""
        user = User.create(Email("wait@example.com"), PasswordHash(HASH))
        uow.users.save(user)
        old = issue_token()
        uow.email_verifications.save(
            EmailVerification.issue(
                user_id=user.id, token_hash=token_digest(old), ttl_hours=24
            )
        )
        queue = Mock()
        queue.enqueue_verification_email.return_value = True

        self._use_case(uow_factory, queue).execute("wait@example.com", context())

        assert uow.email_verifications.claim(token_digest(old)) is None

    def test_an_unknown_address_sends_nothing(self, uow_factory):
        queue = Mock()

        self._use_case(uow_factory, queue).execute("nobody@example.com", context())

        assert not queue.enqueue_verification_email.called

    def test_a_confirmed_account_sends_nothing(self, uow_factory, uow):
        uow.users.save(
            User.create(
                Email("done@example.com"), PasswordHash(HASH), email_verified=True
            )
        )
        queue = Mock()

        self._use_case(uow_factory, queue).execute("done@example.com", context())

        assert not queue.enqueue_verification_email.called

    def test_nothing_raised_where_there_is_nothing_to_send(self, uow_factory):
        """The caller must not be able to tell the cases apart, and an
        exception is the loudest way to tell them."""
        self._use_case(uow_factory, Mock()).execute("nobody@example.com", context())

    def test_a_malformed_address_is_still_refused(self, uow_factory):
        """Refused everywhere else, and saying so reveals nothing."""
        with pytest.raises(ValidationError):
            self._use_case(uow_factory, Mock()).execute("not-an-address", context())


class TestTheMessageItself:
    """Where the link points, and what happens when it cannot be sent."""

    def _use_case(self, mailer, base_url="https://links.example.com"):
        templates = Mock()
        templates.verification_email.return_value = ("Confirm", "body")
        return SendVerificationEmailUseCase(
            mailer=mailer,
            templates=templates,
            logger=Mock(),
            base_url=base_url,
            ttl_hours=24,
        ), templates

    def test_the_link_is_built_from_the_configured_base(self):
        """OWASP: do not build these URLs from the Host header. One an
        attacker chose would mail the victim a link to the attacker's
        server, carrying a working token."""
        use_case, templates = self._use_case(Mock())

        use_case.execute("user@example.com", "TOKEN-123", context())

        url = templates.verification_email.call_args.kwargs["confirm_url"]
        assert url.startswith("https://links.example.com/auth/verify?token=")

    def test_a_trailing_slash_does_not_double(self, ):
        use_case, templates = self._use_case(Mock(), "https://links.example.com/")

        use_case.execute("user@example.com", "TOKEN-123", context())

        url = templates.verification_email.call_args.kwargs["confirm_url"]
        assert "//auth" not in url

    def test_the_token_is_escaped_for_a_query_string(self):
        use_case, templates = self._use_case(Mock())

        use_case.execute("user@example.com", "a b&c=d", context())

        url = templates.verification_email.call_args.kwargs["confirm_url"]
        assert url.endswith("token=a%20b%26c%3Dd")

    def test_the_reader_is_told_how_long_the_link_lives(self):
        use_case, templates = self._use_case(Mock())

        use_case.execute("user@example.com", "TOKEN-123", context())

        assert templates.verification_email.call_args.kwargs["ttl_hours"] == 24

    def test_a_delivery_failure_reaches_the_caller(self):
        """Swallowed here, the queue would count a lost message as sent
        and the retry would never happen."""
        mailer = Mock()
        mailer.send.side_effect = MailDeliveryError("server down")
        use_case, _ = self._use_case(mailer)

        with pytest.raises(MailDeliveryError):
            use_case.execute("user@example.com", "TOKEN-123", context())

    def test_neither_the_token_nor_the_link_is_logged(self):
        """This is the one class that holds the token in the clear and
        builds a URL out of it, and it was the one with no such check.

        The link is a credential for as long as it is valid, and a log is
        read by more people, and kept longer, than a mailbox.
        """
        logger = Mock()
        logger.bind.return_value = logger
        templates = Mock()
        templates.verification_email.return_value = ("Confirm", "body")
        use_case = SendVerificationEmailUseCase(
            mailer=Mock(),
            templates=templates,
            logger=logger,
            base_url="https://links.example.com",
            ttl_hours=24,
        )

        use_case.execute("user@example.com", "SECRET-TOKEN-VALUE", context())

        assert "SECRET-TOKEN-VALUE" not in str(logger.mock_calls)

    def test_a_failed_delivery_logs_no_token_either(self):
        logger = Mock()
        logger.bind.return_value = logger
        templates = Mock()
        templates.verification_email.return_value = ("Confirm", "body")
        mailer = Mock()
        mailer.send.side_effect = MailDeliveryError("server down")
        use_case = SendVerificationEmailUseCase(
            mailer=mailer,
            templates=templates,
            logger=logger,
            base_url="https://links.example.com",
            ttl_hours=24,
        )

        with pytest.raises(MailDeliveryError):
            use_case.execute("user@example.com", "SECRET-TOKEN-VALUE", context())

        assert "SECRET-TOKEN-VALUE" not in str(logger.mock_calls)


class TestTheSweep:
    """Old unconfirmed registrations, and the tokens left behind."""

    def _use_case(self, uow_factory, ttl_hours=72):
        return CleanUnverifiedAccountsUseCase(
            uow_factory=uow_factory,
            logger=Mock(),
            unverified_ttl_hours=ttl_hours,
        )

    @pytest.mark.parametrize("ttl_hours", [13, 200])
    def test_it_asks_for_the_configured_cutoff(self, uow_factory, uow, ttl_hours):
        """A sweep with the wrong window deletes accounts that are still
        waiting, or none at all -- and both look like success.

        The lifetimes here are deliberately not the default. Written
        against 72 -- the value the use case would have used anyway -- this
        compared a number with itself: replacing
        ``hours=self.unverified_ttl_hours`` with a hard-coded 72 left the
        whole suite green, and ``UNVERIFIED_ACCOUNT_TTL_HOURS`` could be
        detached from the sweep entirely without anything noticing.
        """
        expected = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)

        self._use_case(uow_factory, ttl_hours=ttl_hours).execute(context())

        assert uow.users.deleted_before is not None
        drift = abs((uow.users.deleted_before - expected).total_seconds())
        assert drift < 5

    def test_it_deletes_the_ones_that_ran_out_of_time(self, uow_factory, uow):
        stale = User.create(Email("stale@example.com"), PasswordHash(HASH))
        stale.created_at = datetime.now(timezone.utc) - timedelta(hours=100)
        uow.users.save(stale)

        assert self._use_case(uow_factory).execute(context()) == 1

    def test_it_leaves_confirmed_accounts_alone(self, uow_factory, uow):
        settled = User.create(
            Email("settled@example.com"), PasswordHash(HASH), email_verified=True
        )
        settled.created_at = datetime.now(timezone.utc) - timedelta(days=400)
        uow.users.save(settled)

        assert self._use_case(uow_factory).execute(context()) == 0
        assert uow.users.users == [settled]
