"""Registering a taken address must look like registering a free one.

Over HTTP, against the real stack, because this is a property of the
answer a caller receives and not of any one object: the status, the body,
and what the service does behind them all have to match.

What the suite cannot hold is the third channel. The response time was the
loudest of the three -- 290x, ranges nowhere near each other -- and it is
closed by doing equal work, not by asserting a duration here: a clock
assertion on a shared machine fails for reasons that have nothing to do
with registration. The equal work is held one layer down, in
``tests/unit/application/test_use_cases/test_registration_is_anonymous.py``,
and the timing itself is measured by hand and written into the developer
guide.
"""

import pytest
from sqlalchemy import text


PASSWORD = "StrongPass1!"


@pytest.fixture
def taken(client, request):
    """An address that is already registered when the test starts."""
    address = f"taken-{request.node.name}@example.test"
    client.post(
        "/api/v1/auth/register", json={"email": address, "password": PASSWORD}
    )
    return address


@pytest.fixture
def free(request):
    """An address nobody has registered.

    Unique per test: the application fixture is session-scoped, so one
    database serves the whole run and a constant address would be free or
    taken depending on what ran before.
    """
    return f"free-{request.node.name}@example.test"


def _register(client, email):
    return client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    )


def _count_accounts(app, email):
    with app.app_context():
        with app.container.get_db_manager().session() as session:
            return session.execute(
                text("SELECT COUNT(*) FROM users WHERE email = :email"),
                {"email": email},
            ).scalar()


def _count_confirmations(app, email):
    with app.app_context():
        with app.container.get_db_manager().session() as session:
            return session.execute(
                text(
                    "SELECT COUNT(*) FROM email_verifications v "
                    "JOIN users u ON u.id = v.user_id WHERE u.email = :email"
                ),
                {"email": email},
            ).scalar()


class TestTheTwoAnswersAreTheSame:
    """Status and body, compared against each other rather than to a
    literal: a change that moves both together is still indistinguishable,
    and a check against a hard-coded 202 would not say that."""

    def test_the_status_is_the_same(self, client, taken, free):
        assert _register(client, taken).status_code == (
            _register(client, free).status_code
        )

    def test_the_body_is_the_same(self, client, taken, free):
        assert _register(client, taken).get_json() == (
            _register(client, free).get_json()
        )

    def test_the_answer_names_no_account(self, client, taken, free):
        """An id or an address here would be the disclosure the equal
        status was for -- and on the taken path it would be somebody
        else's."""
        for address in (taken, free):
            response = _register(client, address)

            assert set(response.get_json()) == {"message"}
            assert address not in response.get_data(as_text=True)

    def test_it_is_the_success_status_and_not_an_error(self, client, free):
        """Pinned once, so that "the same" cannot become the same 500.

        The comparisons above are satisfied by any two identical answers,
        including two identical failures: a controller answering 500 with
        this same one-key body passes every one of them. The global error
        envelope would not -- it carries ``error``, ``details`` and
        ``timestamp`` -- but a hand-written failure is not obliged to use
        it, and that is the gap this closes.
        """
        assert _register(client, free).status_code == 202


class TestNothingHappensToTheExistingAccount:
    """The second attempt must not create, overwrite or unlock anything."""

    def test_no_second_account_appears(self, client, app, taken):
        _register(client, taken)

        assert _count_accounts(app, taken) == 1

    def test_no_confirmation_is_issued_for_it(self, client, app, taken):
        """The first registration left one. A second would mean mailing a
        working link for an account to whoever guessed its address."""
        before = _count_confirmations(app, taken)

        _register(client, taken)

        assert _count_confirmations(app, taken) == before

    def test_the_password_is_not_changed(self, client, app, taken):
        """Otherwise registering over somebody's address would be a way to
        take it: type the address, choose a password, wait for the reply
        that says nothing."""
        client.post(
            "/api/v1/auth/register",
            json={"email": taken, "password": "DifferentPass9!"},
        )

        from tests.integration.conftest import confirm_email

        confirm_email(app, taken)
        assert client.post(
            "/api/v1/auth/login",
            json={"email": taken, "password": "DifferentPass9!"},
        ).status_code == 401
        assert client.post(
            "/api/v1/auth/login",
            json={"email": taken, "password": PASSWORD},
        ).status_code == 200


class TestWhatIsStillRefusedOutLoud:
    """Refusals about the request itself stay visible: they describe what
    the caller sent, not who is registered."""

    def test_a_malformed_address_is_still_refused(self, client):
        response = _register(client, "not-an-address")

        assert response.status_code == 400

    def test_a_password_the_policy_refuses_is_still_refused(
        self, client, free
    ):
        response = client.post(
            "/api/v1/auth/register", json={"email": free, "password": "123"}
        )

        assert response.status_code == 400

    def test_the_refusal_is_the_same_for_a_taken_address(
        self, client, taken
    ):
        """The password is judged before the address is looked up, so a
        weak password on a taken address answers like a weak password on a
        free one -- rather than 202, which would say the address exists.
        """
        response = client.post(
            "/api/v1/auth/register", json={"email": taken, "password": "123"}
        )

        assert response.status_code == 400
