"""Capitalisation must not buy a second account, over HTTP.

The value object lowers the address, but whether that reaches the unique
index is a property of every layer between: the controller, the use case,
the repository and the column. This is the test that would have caught the
defect as it actually appeared -- registering the same mailbox twice with
different capitalisation and getting two rows, two confirmation links, and
a sign-in whose success depended on which spelling was typed first.
"""

import pytest
from sqlalchemy import text


PASSWORD = "StrongPass1!"


@pytest.fixture
def mailbox(request):
    """One mailbox, spelled lower case, unique to this test."""
    return f"case-{request.node.name}@example.test".lower()


def _register(client, email):
    return client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    )


def _rows_for(app, mailbox):
    with app.app_context():
        with app.container.get_db_manager().session() as session:
            return session.execute(
                text("SELECT email FROM users WHERE lower(email) = :m"),
                {"m": mailbox},
            ).scalars().all()


class TestASecondCapitalisationIsNotASecondAccount:
    """One mailbox, one row, whatever was typed."""

    def test_registering_it_shouted_creates_nothing_new(
        self, client, app, mailbox
    ):
        _register(client, mailbox)

        _register(client, mailbox.upper())

        assert _rows_for(app, mailbox) == [mailbox]

    def test_the_second_attempt_is_answered_like_any_other(
        self, client, mailbox
    ):
        """Says nothing on its own, and is here for what it rules out.

        Registration answers 202 whether an address is taken or free, so
        no status could reveal that the two spellings met -- which is the
        point: closing the case gap must not open a way to ask about it.
        The account count beside it is what actually holds the merge.
        """
        _register(client, mailbox)

        assert _register(client, mailbox.title()).status_code == 202

    def test_the_stored_address_is_the_lower_case_one(
        self, client, app, mailbox
    ):
        """Registered shouted from the start, it is still stored quiet:
        every later comparison is against this string."""
        _register(client, mailbox.upper())

        assert _rows_for(app, mailbox) == [mailbox]


class TestSigningInIgnoresCapitalisation:
    """Whatever was typed at registration, any spelling signs in."""

    @pytest.fixture
    def registered(self, client, app, mailbox):
        """An account registered shouted, and confirmed."""
        _register(client, mailbox.upper())
        from tests.integration.conftest import confirm_email

        confirm_email(app, mailbox)
        return mailbox

    @pytest.mark.parametrize("spelling", ["lower", "upper", "title"])
    def test_any_spelling_signs_in(self, app, registered, spelling):
        typed = getattr(registered, spelling)()

        # A fresh client per attempt: one that has signed in carries
        # cookies, and the CSRF layer refuses the next write before any
        # credentials are looked at.
        response = app.test_client().post(
            "/api/v1/auth/login", json={"email": typed, "password": PASSWORD}
        )

        assert response.status_code == 200, response.get_json()


class TestTheConfirmationFollowsTheSameAddress:
    """The link is mailed to the address the account is stored under."""

    def test_a_shouted_registration_confirms_the_stored_account(
        self, client, app, mailbox
    ):
        """Registration lowers the address; the confirmation row hangs off
        the account under that same string, so the link that arrives
        confirms the account that exists."""
        _register(client, mailbox.upper())

        with app.app_context():
            with app.container.get_db_manager().session() as session:
                count = session.execute(
                    text(
                        "SELECT COUNT(*) FROM email_verifications v "
                        "JOIN users u ON u.id = v.user_id "
                        "WHERE u.email = :m"
                    ),
                    {"m": mailbox},
                ).scalar()

        assert count == 1
