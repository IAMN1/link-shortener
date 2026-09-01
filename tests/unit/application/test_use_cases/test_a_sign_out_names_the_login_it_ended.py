"""
The record of a sign-out says *which* login ended.

``SESSION_ENDED`` exists so an operator can tell a session that was closed
from one still open, and the field that identifies it is ``session_id`` --
the chain. The use case took the chain from its ``session_id`` argument
only, which the controller fills from the access token's ``sid``. A client
holding **only** a refresh token therefore wrote the event with the field
empty, and that client is the ordinary one: an access token lives minutes,
a refresh token days, so "sign me out" arrives from a caller whose access
token has expired more often than not.

Measured before the fix, signing out with a refresh token and nothing else::

    Security event: SESSION_ENDED ... session_id=None target_user_id=77f2...

The comment at that branch claimed the token carried the chain -- "the two
facts the record needs ... are what the token itself carries". It does not:
``sid`` is a claim of an *access* token, and a refresh token carries
``jti``, which names its row. The row is where the chain is, so the row is
read.
"""

from unittest.mock import MagicMock

from link_shortener.application.context import RequestContext
from link_shortener.application.use_cases.auth.sign_out import SignOutUseCase


CHAIN = "the-chain"
JTI = "the-row"
OWNER = "the-account"


def a_use_case(row=None, revoked=True):
    """The use case with every port stubbed, and the row it will read."""
    auth = MagicMock()
    auth.validate_token.return_value = {"sub": OWNER, "jti": JTI}
    auth.revoke_refresh_token.return_value = revoked

    uow = MagicMock()
    uow.refresh_sessions.find_by_token_id.return_value = row
    uow.__enter__.return_value = uow
    uow.__exit__.return_value = False

    audit = MagicMock()
    # ``BaseUseCase._get_audit_logger`` binds the request context and uses
    # what ``bind`` hands back, so the calls land on that object rather
    # than on this one unless the two are the same.
    audit.bind.return_value = audit
    return SignOutUseCase(
        authentication_service=auth,
        uow_factory=MagicMock(return_value=uow),
        audit_logger=audit,
        logger=MagicMock(),
    ), audit, uow


def a_row(chain=CHAIN):
    """A session row, which is the only thing that knows the chain."""
    row = MagicMock()
    row.chain_id = chain
    return row


def context():
    return RequestContext(request_id="sign-out-test")


class TestASignOutByRefreshTokenAlone:

    def test_the_record_names_the_chain(self):
        """The case the fix is for."""
        use_case, audit, _ = a_use_case(row=a_row())

        assert use_case.execute(context(), refresh_token="a-token") is True

        _, kwargs = audit.log_session_ended.call_args
        assert kwargs["session_id"] == CHAIN

    def test_the_row_is_found_by_the_claim_the_token_actually_carries(self):
        """
        ``jti``, not ``sid``.

        Asked by the wrong claim the lookup returns nothing and the field
        goes back to being empty, which is the defect wearing a new name.
        """
        use_case, _, uow = a_use_case(row=a_row())

        use_case.execute(context(), refresh_token="a-token")

        uow.refresh_sessions.find_by_token_id.assert_called_once_with(JTI)

    def test_the_account_is_still_named(self):
        """What already worked has to go on working."""
        use_case, audit, _ = a_use_case(row=a_row())

        use_case.execute(context(), refresh_token="a-token")

        _, kwargs = audit.log_session_ended.call_args
        assert kwargs["target_user_id"] == OWNER

    def test_a_row_that_is_not_there_records_the_act_anyway(self):
        """
        The sign-out happened; only the chain is unknown.

        Losing the record because one field could not be filled would be a
        worse answer than the empty field this replaces.
        """
        use_case, audit, _ = a_use_case(row=None)

        use_case.execute(context(), refresh_token="a-token")

        audit.log_session_ended.assert_called_once()
        assert audit.log_session_ended.call_args[1]["session_id"] is None


class TestASignOutByAccessTokenAlone:
    """The other door, which already named the chain and still must."""

    def test_the_chain_comes_from_the_argument(self):
        use_case, audit, uow = a_use_case()
        use_case.authentication_service.revoke_session_chain.return_value = 1

        assert use_case.execute(context(), session_id="from-the-sid") is True

        _, kwargs = audit.log_session_ended.call_args
        assert kwargs["session_id"] == "from-the-sid"
        uow.refresh_sessions.find_by_token_id.assert_not_called()

    def test_a_refresh_token_does_not_override_a_named_chain(self):
        """
        Both arrive together from the controller, and the ``sid`` is the
        one the caller authenticated with.
        """
        use_case, audit, uow = a_use_case(row=a_row("a-different-chain"))

        use_case.execute(
            context(), refresh_token="a-token", session_id="from-the-sid"
        )

        assert audit.log_session_ended.call_args[1]["session_id"] == (
            "from-the-sid"
        )
        uow.refresh_sessions.find_by_token_id.assert_not_called()
