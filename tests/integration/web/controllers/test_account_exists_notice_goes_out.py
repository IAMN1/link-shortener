"""The notice that an address is already registered, on the live path.

Two things are only true together here. First, that registering a taken
address causes a message to be built at all: with ``CELERY_ENABLED=false``,
the shipped default, that depends on one wiring line in the container, and
removing it leaves the notice unsent -- which is not merely a missing
courtesy. The free path submits a message on the request thread and the
taken path would not, so the two would stop taking the same time, and the
timing channel this whole change closed would reopen with the suite still
green.

Second, that the message says only what it may. It goes to an address the
caller may not own, on nothing but a guess, so it must carry no token and
point at nothing a stranger could use.
"""

import pytest

from link_shortener.application.ports.mailer import Mailer


PASSWORD = "StrongPass1!"


class RecordingMailer(Mailer):
    """A mailer that keeps what it was asked to send."""

    def __init__(self):
        self.messages = []

    def send(self, to, subject, body):
        self.messages.append({"to": to, "subject": subject, "body": body})


@pytest.fixture
def outbox(app):
    """Replace the mailer on both live paths and hand back what it caught.

    Reached through the queue's synchronous fallbacks, which are the
    objects that actually send during a run: the container wires them when
    Celery is off. Going through that wiring rather than around it is the
    point -- if it disappears, this fixture fails instead of quietly
    testing nothing.
    """
    with app.app_context():
        queue = app.container.get_task_queue()

        notice_fn = getattr(queue, "_send_account_exists_fn", None)
        assert notice_fn is not None, (
            "nothing is wired to send the account-exists notice: a taken "
            "address would answer without sending, and the two registration "
            "paths would stop costing the same"
        )
        confirm_fn = getattr(queue, "_send_verification_fn", None)
        assert confirm_fn is not None

        recorder = RecordingMailer()
        originals = [(fn.__self__, fn.__self__.mailer) for fn in
                     (notice_fn, confirm_fn)]
        for use_case, _ in originals:
            use_case.mailer = recorder
        try:
            yield recorder
        finally:
            for use_case, original in originals:
                use_case.mailer = original


@pytest.fixture
def taken(client, request, outbox):
    """An address registered before the test starts, mail and all.

    The confirmation that registration sends is caught by the same
    recorder, so the outbox is emptied afterwards: what each test wants to
    look at is the message its own call produced.
    """
    address = f"notice-{request.node.name}@example.test"
    client.post(
        "/api/v1/auth/register", json={"email": address, "password": PASSWORD}
    )
    outbox.messages.clear()
    return address


def _register(client, email, password=PASSWORD):
    return client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )


class TestBothPathsSendExactlyOneMessage:
    """The count is the part that keeps the two paths the same length."""

    def test_a_taken_address_sends_one(self, client, outbox, taken):
        _register(client, taken)

        assert len(outbox.messages) == 1

    def test_a_free_address_sends_one(self, client, outbox, request):
        _register(client, f"free-{request.node.name}@example.test")

        assert len(outbox.messages) == 1

    def test_it_goes_to_the_address_that_was_typed(
        self, client, outbox, taken
    ):
        _register(client, taken)

        assert outbox.messages[0]["to"] == taken


class TestTheNoticeSaysOnlyWhatItMay:
    """Sent to somebody who did not ask, on a stranger's say-so."""

    def test_it_carries_no_confirmation_link(self, client, outbox, taken):
        """A link here would confirm an address on behalf of whoever
        guessed it -- and it would be a working one."""
        _register(client, taken)

        assert "/auth/verify" not in outbox.messages[0]["body"]
        assert "token" not in outbox.messages[0]["body"].lower()

    def test_it_points_at_the_sign_in_page(self, client, outbox, taken, app):
        _register(client, taken)

        expected = app.config["BASE_URL"].rstrip("/") + "/login"
        assert expected in outbox.messages[0]["body"]

    def test_it_is_not_the_confirmation_message(self, client, outbox, taken):
        """The two must be different messages. Sending the confirmation
        template here would make the notice indistinguishable from a real
        registration to the person receiving it."""
        _register(client, taken)
        subject = outbox.messages[0]["subject"]

        assert subject != "Confirm your email address"
        assert subject


class TestASuppliedHostDoesNotReachTheNotice:
    """The base of the URL is configuration, never a header."""

    @pytest.mark.parametrize(
        "host", ["evil.attacker.example", "testserver:8080", "localhost"]
    )
    def test_the_host_header_is_ignored(self, client, outbox, taken, host):
        client.post(
            "/api/v1/auth/register",
            json={"email": taken, "password": PASSWORD},
            headers={"Host": host},
        )

        assert host not in outbox.messages[0]["body"]
