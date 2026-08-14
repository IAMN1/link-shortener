"""Where the confirmation link points, measured on the live path.

Two things are only true together, and neither was checked. First, that
registering actually causes a message to be built at all -- with
``CELERY_ENABLED=false``, which is the shipped default, that depends on
one wiring line in the container, and removing it leaves every
registration answering 201 and sending nothing. Second, that the link in
that message comes from the configured base and not from the request.

OWASP's Forgot Password Cheat Sheet asks for the second by name: "Don't
rely on the Host header while creating the reset URLs to avoid Host Header
Injection attacks. The URL should either be hard-coded, or validated
against a list of trusted domains." A ``Host`` an attacker chooses would
mail the victim a link to the attacker's server, carrying a live token.
"""

from urllib.parse import urlsplit

import pytest

from link_shortener.application.ports.mailer import Mailer
from link_shortener.application.use_cases.auth.send_verification_email import (
    VERIFY_PATH,
)


class RecordingMailer(Mailer):
    """A mailer that keeps what it was asked to send."""

    def __init__(self):
        self.messages = []

    def send(self, to, subject, body):
        self.messages.append({"to": to, "subject": subject, "body": body})


@pytest.fixture
def outbox(app):
    """Replace the mailer on the live path and hand back what it caught.

    Reaches the use case through the queue's synchronous fallback, which
    is the object that actually sends during a test run: the container
    wires ``SendVerificationEmailUseCase.execute`` in there when Celery is
    off. Going through that wiring rather than around it is deliberate --
    if the wiring disappears, this fixture fails instead of quietly
    testing nothing.
    """
    with app.app_context():
        queue = app.container.get_task_queue()
        send_fn = getattr(queue, "_send_verification_fn", None)
        assert send_fn is not None, (
            "nothing is wired to send confirmation mail: registration would "
            "answer 201 and send nothing"
        )

        use_case = send_fn.__self__
        original = use_case.mailer
        recorder = RecordingMailer()
        use_case.mailer = recorder
        try:
            yield recorder
        finally:
            use_case.mailer = original


class TestTheMessageIsActuallySent:
    """The wiring that makes a registration produce a message."""

    def test_registering_sends_one_message(self, client, outbox):
        client.post(
            "/api/v1/auth/register",
            json={"email": "outbox-one@example.test", "password": "StrongPass1!"},
        )

        assert len(outbox.messages) == 1

    def test_it_goes_to_the_address_that_registered(self, client, outbox):
        client.post(
            "/api/v1/auth/register",
            json={"email": "outbox-two@example.test", "password": "StrongPass1!"},
        )

        assert outbox.messages[0]["to"] == "outbox-two@example.test"

    def test_it_carries_a_confirmation_link(self, client, outbox):
        client.post(
            "/api/v1/auth/register",
            json={"email": "outbox-three@example.test", "password": "StrongPass1!"},
        )

        assert f"{VERIFY_PATH}?token=" in outbox.messages[0]["body"]

    def test_the_link_in_it_works(self, client, outbox):
        """End to end: the address in the message is followed as it was
        written. Taking the token out and putting it on a path of the
        test's own choosing would pass while the mailed link answered
        404."""
        client.post(
            "/api/v1/auth/register",
            json={"email": "outbox-four@example.test", "password": "StrongPass1!"},
        )
        body = outbox.messages[0]["body"]
        link = next(
            word for word in body.split() if "verify?token=" in word
        )

        response = client.get(urlsplit(link).path + "?" + urlsplit(link).query)

        assert response.status_code == 200

    def test_asking_again_sends_another(self, client, outbox):
        client.post(
            "/api/v1/auth/register",
            json={"email": "outbox-five@example.test", "password": "StrongPass1!"},
        )
        client.post(
            "/api/v1/auth/resend-verification",
            json={"email": "outbox-five@example.test"},
        )

        assert len(outbox.messages) == 2

    def test_it_goes_to_the_stored_address_and_not_the_typed_one(
        self, client, outbox
    ):
        """Asked for with different capitalisation, the link still goes to
        the address the account is stored under -- which is the one the
        token belongs to."""
        client.post(
            "/api/v1/auth/register",
            json={"email": "outbox-six@example.test", "password": "StrongPass1!"},
        )
        outbox.messages.clear()

        client.post(
            "/api/v1/auth/resend-verification",
            json={"email": "OUTBOX-SIX@EXAMPLE.TEST"},
        )

        assert outbox.messages[0]["to"] == "outbox-six@example.test"


class TestTheLinkIgnoresTheRequest:
    """The base of the URL is configuration, never a header."""

    @pytest.mark.parametrize(
        "host",
        [
            "evil.attacker.example",
            "testserver:8080",
            "localhost",
        ],
    )
    def test_a_supplied_host_does_not_reach_the_link(self, client, outbox, host):
        client.post(
            "/api/v1/auth/register",
            json={
                "email": f"host-{host.replace(':', '-')}@example.test",
                "password": "StrongPass1!",
            },
            headers={"Host": host},
        )

        body = outbox.messages[0]["body"]
        assert host not in body, body

    def test_the_link_is_built_on_the_configured_base(self, client, app, outbox):
        client.post(
            "/api/v1/auth/register",
            json={"email": "base-url@example.test", "password": "StrongPass1!"},
            headers={"Host": "evil.attacker.example"},
        )

        base = app.container.config.BASE_URL.rstrip("/")
        assert outbox.messages[0]["body"].count(f"{base}{VERIFY_PATH}?token=") == 1

    def test_a_forwarded_host_does_not_reach_it_either(self, client, outbox):
        """The header a proxy would set, which is not trusted here."""
        client.post(
            "/api/v1/auth/register",
            json={"email": "forwarded@example.test", "password": "StrongPass1!"},
            headers={"X-Forwarded-Host": "evil.attacker.example"},
        )

        assert "evil.attacker.example" not in outbox.messages[0]["body"]
