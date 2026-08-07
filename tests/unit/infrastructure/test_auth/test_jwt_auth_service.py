"""Unit tests for the JWT authentication service.

Concentrates on what a token must prove before it is believed, and on the
part of the contract that is deliberately left to the caller.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import jwt
import pytest

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
