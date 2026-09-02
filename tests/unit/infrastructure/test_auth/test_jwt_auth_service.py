"""Unit tests for the JWT authentication service.

Concentrates on what a token must prove before it is believed, and on the
part of the contract that is deliberately left to the caller.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import jwt
import pytest

from link_shortener.domain.entities.refresh_session import RefreshSession
from link_shortener.domain.exceptions import RefreshTokenReplayedError
from link_shortener.domain.entities.role import Role
from link_shortener.domain.entities.user import User
from link_shortener.domain.value_objects.email import Email
from link_shortener.domain.value_objects.password_hash import PasswordHash
from link_shortener.infrastructure.auth.jwt_auth_service import (
    JwtAuthenticationService,
)


SECRET = "unit-test-secret"
ALGORITHM = "HS256"


@pytest.fixture
def uow_factory():
    """A Unit of Work factory whose session yields configurable repositories."""
    uow = MagicMock()
    factory = MagicMock()
    factory.return_value.__enter__.return_value = uow
    factory.uow = uow
    return factory


@pytest.fixture
def service(uow_factory):
    """Service under test, wired to mock persistence."""
    return JwtAuthenticationService(
        uow_factory=uow_factory,
        secret_key=SECRET,
        access_expire_minutes=15,
        refresh_expire_days=7,
        algorithm=ALGORITHM,
    )


def mint(**claims) -> str:
    """Sign an arbitrary claim set with the service's key.

    Signed correctly on purpose: these tests are about which claims a token
    must carry, not about whether the signature is checked.

    Args:
        **claims: Claims to put in the payload.

    Returns:
        Encoded JWT.
    """
    return jwt.encode(claims, SECRET, algorithm=ALGORITHM)


def full_claims(**overrides) -> dict:
    """Build a claim set this service would itself issue.

    Args:
        **overrides: Claims to replace or add.

    Returns:
        Claim dictionary.
    """
    claims = {
        "sub": "user-1",
        "email": "someone@example.com",
        "roles": ["user"],
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
        "iat": datetime.now(timezone.utc),
    }
    claims.update(overrides)
    return claims


class TestRequiredClaims:
    """A correctly signed token is not automatically a usable one."""

    def test_a_complete_token_is_accepted(self, service):
        """The control: without this the rejections below prove nothing."""
        assert service.validate_token(mint(**full_claims())) is not None

    def test_token_without_expiry_is_rejected(self, service):
        """A token with no ``exp`` must not become a permanent one.

        PyJWT verifies expiry only when the claim is present, so an
        expiry-less token was accepted and then never expired -- the one
        failure mode that outlives every other control here.
        """
        claims = full_claims()
        del claims["exp"]

        assert service.validate_token(mint(**claims)) is None

    def test_token_without_subject_is_rejected(self, service):
        """Every caller reads ``sub``; absent, it arrives as None."""
        claims = full_claims()
        del claims["sub"]

        assert service.validate_token(mint(**claims)) is None

    def test_token_without_type_is_rejected(self, service):
        """Without ``type`` an access check has nothing to compare."""
        claims = full_claims()
        del claims["type"]

        assert service.validate_token(mint(**claims)) is None

    def test_expired_token_is_still_rejected(self, service):
        """Requiring the claim must not stop it from being checked."""
        claims = full_claims(
            exp=datetime.now(timezone.utc) - timedelta(seconds=1)
        )

        assert service.validate_token(mint(**claims)) is None

    def test_type_mismatch_is_rejected(self, service):
        """A refresh token must not pass where an access token is expected."""
        token = mint(**full_claims(type="refresh"))

        assert service.validate_token(token, expected_type="access") is None
        assert service.validate_token(token, expected_type="refresh") is not None


class TestSignatureIsVerified:
    """The claims are only worth reading if the signature was checked.

    Nothing asserted this. A mutation run turning off ``verify_signature``
    left all 1182 tests green -- every other test here signs with the real
    key, so none of them can tell a checked signature from an unchecked one.
    """

    def test_a_token_signed_with_another_key_is_rejected(self, service):
        """Anyone can mint claims; only the key holder can sign them."""
        forged = jwt.encode(
            full_claims(sub="attacker"), "not-the-service-key", algorithm=ALGORITHM
        )

        assert service.validate_token(forged) is None

    def test_an_unsigned_token_is_rejected(self, service):
        """``alg: none`` is the oldest way around a signature check."""
        unsigned = jwt.encode(full_claims(), key="", algorithm="none")

        assert service.validate_token(unsigned) is None

    def test_a_tampered_payload_is_rejected(self, service):
        """Editing a claim in a real token must invalidate it.

        The closest case to a genuine attack: the token was issued by this
        service, and one field is changed afterwards.
        """
        import base64
        import json

        header, payload, signature = mint(**full_claims()).split(".")
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        claims = json.loads(raw)
        claims["sub"] = "somebody-else"
        edited = (
            base64.urlsafe_b64encode(json.dumps(claims).encode())
            .decode()
            .rstrip("=")
        )

        assert service.validate_token(f"{header}.{edited}.{signature}") is None


class TestWhatTheTokenStates:
    """A token states who is calling, and not what they may do.

    It used to carry a ``roles`` claim. Nothing decided anything by it --
    the middleware reads the account from the database on every request,
    which is what makes a demotion take effect at once -- so what the
    claim actually was is a snapshot up to fifteen minutes stale, sitting
    in the token looking authoritative. The one reader was
    ``flask security validate-token``, printing it as diagnostics.
    """

    @staticmethod
    def _somebody() -> User:
        """A user wearing a role, so an omitted claim is not a coincidence."""
        return User(
            id="user-7",
            email=Email("wearer@example.com"),
            password_hash=PasswordHash("$2b$12$" + "a" * 53),
            roles=[Role(id="role-1", name="admin")],
        )

    def _claims(self, service, token):
        """Decode without verifying: the subject here is the payload."""
        return jwt.decode(
            token, SECRET, algorithms=[ALGORITHM],
            options={"verify_exp": False},
        )

    def test_an_access_token_states_no_roles(self, service):
        token = service._create_token(
            self._somebody(), timedelta(minutes=15), "access",
            session_id="session-1",
        )

        claims = self._claims(service, token)
        assert "roles" not in claims
        assert claims["sub"] == "user-7"

    def test_a_refresh_token_states_no_roles_either(self, service):
        token = service._create_token(
            self._somebody(), timedelta(days=7), "refresh",
            token_id="jti-1",
        )

        assert "roles" not in self._claims(service, token)


class TestAuthenticateContract:
    """``authenticate`` answers about the password, not about admission."""

    @staticmethod
    def _user(service, *, is_active: bool) -> User:
        """Build a user whose password is 'CorrectHorse42!'."""
        return User(
            id="user-1",
            email=Email("someone@example.com"),
            password_hash=PasswordHash(
                service.hash_password("CorrectHorse42!")
            ),
            roles=[],
            is_active=is_active,
        )

    def test_correct_password_returns_the_user(self, service, uow_factory):
        """The control for the case below."""
        user = self._user(service, is_active=True)
        uow_factory.uow.users.find_by_email.return_value = user

        assert service.authenticate("someone@example.com", "CorrectHorse42!") is user

    def test_deactivated_account_is_still_returned(self, service, uow_factory):
        """Documented on the port: admission is the caller's decision.

        Pinned by a test because it is the kind of contract a reader
        assumes the other way round. The login use case is what refuses a
        deactivated account, and it answers exactly as it does for a wrong
        password while logging the two apart -- a distinction that would be
        lost if this method collapsed both into None.
        """
        user = self._user(service, is_active=False)
        uow_factory.uow.users.find_by_email.return_value = user

        returned = service.authenticate("someone@example.com", "CorrectHorse42!")

        assert returned is user
        assert returned.is_active is False

    def test_wrong_password_returns_none(self, service, uow_factory):
        """The one thing this method does decide."""
        uow_factory.uow.users.find_by_email.return_value = self._user(
            service, is_active=True
        )

        assert service.authenticate("someone@example.com", "WrongGuess42!") is None


class TestASessionBelongsToOneAccount:
    """A ``jti`` names a session; ``sub`` says whose it must be.

    Both revocation and rotation check that the two agree, and neither
    check was reached by anything. A guard nothing exercises is a guard
    that can be inverted -- or dropped in a refactor -- with the suite
    still green, and what it guards is a caller ending or spending a
    session that is not theirs.

    A token with mismatched claims is not something the service will ever
    mint, so getting here at all means the signing key has gone. That is
    exactly when the last check standing has to be the right one.
    """

    @staticmethod
    def _a_session_of(user_id, token_id):
        """A live session row belonging to one account."""
        return RefreshSession.create(
            user_id=user_id,
            token_id=token_id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )

    def test_revocation_refuses_a_token_naming_another_account(
        self, service, uow_factory
    ):
        uow_factory.uow.refresh_sessions.find_by_token_id.return_value = (
            self._a_session_of("the-owner", "their-session")
        )

        revoked = service.revoke_refresh_token(mint(
            sub="somebody-else",
            jti="their-session",
            type="refresh",
            exp=datetime.now(timezone.utc) + timedelta(days=1),
        ))

        assert revoked is False
        uow_factory.uow.refresh_sessions.revoke_chain.assert_not_called()

    def test_revocation_refuses_a_token_naming_no_session(
        self, service, uow_factory
    ):
        uow_factory.uow.refresh_sessions.find_by_token_id.return_value = None

        revoked = service.revoke_refresh_token(mint(
            sub="the-owner",
            jti="no-such-session",
            type="refresh",
            exp=datetime.now(timezone.utc) + timedelta(days=1),
        ))

        assert revoked is False
        uow_factory.uow.refresh_sessions.revoke_chain.assert_not_called()

    def test_revocation_refuses_a_token_carrying_no_jti(self, service):
        """``jti`` is not in ``REQUIRED_CLAIMS``, so it can be absent.

        Absent it arrives as ``None``, which would be looked up as a
        session id of ``None`` -- and a repository answering the first
        row for it would end somebody's session at random.
        """
        assert service.revoke_refresh_token(mint(
            sub="the-owner",
            type="refresh",
            exp=datetime.now(timezone.utc) + timedelta(days=1),
        )) is False

    def test_rotation_refuses_a_token_naming_another_account(
        self, service, uow_factory
    ):
        uow_factory.uow.refresh_sessions.find_by_token_id.return_value = (
            self._a_session_of("the-owner", "their-session")
        )

        pair = service.refresh_access_token(mint(
            sub="somebody-else",
            jti="their-session",
            type="refresh",
            exp=datetime.now(timezone.utc) + timedelta(days=1),
        ))

        assert pair is None
        uow_factory.uow.refresh_sessions.claim_for_rotation.assert_not_called()


class TestAReplayedRefreshTokenRetiresItsChainAndNoMore:
    """
    How far a replay reaches, held against the sentence that describes it.

    Presenting a refresh token that was already spent means one of two
    things and there is no telling which: the honest holder replayed it,
    or a copy did. Either way the chain it belongs to is retired. What
    the code has always done is retire *that chain* -- the comment at the
    branch says so, and gives the reason: revoking the account's every
    session would let anyone holding one dead token sign the victim out
    of every other device they use.

    The summary line of the same method said the opposite -- "every
    session of the user is revoked" -- and nothing compared the two. A
    reader deciding whether a leaked token is a whole-account incident
    would have read the summary, which is the line an editor sees first.

    Held on the seam rather than through the repository: ``revoke_chain``
    and ``revoke_all_for_user`` are two different methods, and which one
    is called is the whole of the difference.
    """

    def _spent_session(self, user_id: str, token_id: str, chain_id: str):
        """A session row that has already been rotated once."""
        session = RefreshSession.create(
            user_id=user_id,
            token_id=token_id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            chain_id=chain_id,
        )
        session.replaced_by = "the-successor"
        return session

    def _replay(self, service, uow_factory):
        """Present a spent token and hand back what the service raised."""
        uow_factory.uow.refresh_sessions.find_by_token_id.return_value = (
            self._spent_session("the-owner", "spent-token", "chain-one")
        )
        with pytest.raises(RefreshTokenReplayedError) as raised:
            service.refresh_access_token(mint(
                sub="the-owner",
                jti="spent-token",
                type="refresh",
                exp=datetime.now(timezone.utc) + timedelta(days=1),
            ))
        return raised.value

    def test_the_replay_is_refused(self, service, uow_factory):
        """
        And says so out loud, rather than answering "no" like an expiry.

        It used to return ``None``, which is what an expired or forged
        token gets, so the one event meaning "this credential is loose"
        was indistinguishable from the ordinary end of a session to
        everything above -- and went into no journal.
        """
        replay = self._replay(service, uow_factory)

        assert replay.user_id == "the-owner"
        assert replay.chain_id == "chain-one"

    def test_the_chain_the_token_belongs_to_is_retired(
        self, service, uow_factory
    ):
        self._replay(service, uow_factory)

        uow_factory.uow.refresh_sessions.revoke_chain.assert_called_once_with(
            "chain-one"
        )

    def test_the_accounts_other_sessions_are_left_alone(
        self, service, uow_factory
    ):
        """
        The half the summary line got wrong.

        ``revoke_all_for_user`` exists and is what deactivating an account
        and resetting a password both call. A replay must not reach it.
        """
        self._replay(service, uow_factory)

        uow_factory.uow.refresh_sessions.revoke_all_for_user.assert_not_called()

    def test_the_sentence_describing_it_does_not_promise_more(self):
        """
        The summary must not claim a reach the branch does not have.

        Read off the method's own docstring, because that is the sentence
        a reader meets and the one that was wrong.
        """
        described = JwtAuthenticationService.refresh_access_token.__doc__ or ""

        assert "every session of the" not in described, described
