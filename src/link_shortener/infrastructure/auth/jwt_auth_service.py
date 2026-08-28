from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
import secrets
import uuid
import bcrypt
import jwt

from link_shortener.application import UnitOfWorkFactory, AuthenticationService
from link_shortener.application.dtos.auth import RefreshedTokens
from link_shortener.domain import User, Email, RefreshSession
from link_shortener.domain.policies.password_policy import validate_password


class JwtAuthenticationService(AuthenticationService):
    """
    Concrete authentication service backed by JSON Web Tokens.

    Responsibilities:
        - Hash and verify passwords with bcrypt.
        - Authenticate users by email/password against the database.
        - Create and validate signed JWT access and refresh tokens.
        - Refresh expired access tokens using a valid refresh token.
    """
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        secret_key: str,
        access_expire_minutes: int,
        refresh_expire_days: int,
        algorithm: str = "HS256"
    ):
        """
        Args:
            uow_factory: Factory for creating Unit of Work instances.
            secret_key: Secret used to sign JWT tokens.
            access_expire_minutes: Lifetime of an access token in minutes.
            refresh_expire_days: Lifetime of a refresh token in days.
            algorithm: JWT signing algorithm (default HS256).
        """
        self.uow_factory = uow_factory
        self.secret_key = secret_key
        self.access_expire = timedelta(minutes=access_expire_minutes)
        self.refresh_expire = timedelta(days=refresh_expire_days)
        self.algorithm = algorithm
        self._decoy_hash: Optional[str] = None

    def _get_decoy_hash(self) -> str:
        """
        Return a throwaway hash used to equalise timing on unknown accounts.

        Built on first use rather than in ``__init__`` so that constructing
        the service stays cheap.

        Returns:
            A real bcrypt hash of a random value.
        """
        if self._decoy_hash is None:
            self._decoy_hash = self.hash_password(secrets.token_urlsafe(16))
        return self._decoy_hash

    def hash_password(self, plain: str) -> str:
        """
        Hash a plain-text password using bcrypt.

        Args:
            plain: Raw password.

        Returns:
            Hashed password string.

        Raises:
            ValidationError: If the password does not meet the policy.
        """
        # Checked against the domain policy, not against bcrypt's own limit:
        # the client is told the service's rule, not which library enforces
        # it. Checked here rather than in the registration use case because
        # every path that sets a password goes through hashing -- the API,
        # the admin endpoints and the CLI alike -- and a rule enforced in
        # one of them is a rule with a way around it.
        validate_password(plain)

        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password=plain.encode(), salt=salt).decode()

    def verify_password(self, plain: str, hashed: str) -> bool:
        """
        Compare a plain-text password against a bcrypt hash.

        A password bcrypt cannot process, or a stored hash it cannot parse,
        counts as a mismatch rather than an error: letting those raise would
        make failed logins distinguishable from unknown accounts.

        Args:
            plain: Raw password.
            hashed: Stored hash.

        Returns:
            True if they match.
        """
        try:
            return bcrypt.checkpw(
                password=plain.encode(), hashed_password=hashed.encode()
            )
        except ValueError:
            return False

    def authenticate(self, email: str, password: str) -> Optional[User]:
        """
        Verify a password against an account.

        Checks the password and nothing else. A deactivated account whose
        password is correct comes back like any other -- see the port for
        why the decision is left to the caller -- so whoever calls this must
        check ``user.is_active`` before granting anything.

        Args:
            email: User email.
            password: Raw password.

        Returns:
            User entity if the password is correct -- active or not --
            else None.
        """
        with self.uow_factory(read_only=True) as uow:
            user = uow.users.find_by_email(Email(email))
            if not user:
                # Hash against a decoy anyway. Returning early here made an
                # unknown account answer in under a millisecond while a real
                # one took ~160ms, which told an attacker which emails are
                # registered without any need for statistics.
                self.verify_password(password, self._get_decoy_hash())
                return None
            if not self.verify_password(password, user.password_hash.value):
                return None
            # Return a detached entity (session will be closed).
            return user

    def _create_token(
        self,
        user: User,
        expires_delta: timedelta,
        token_type: str,
        token_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """
        Internal helper to build a signed JWT.

        The payload includes ``sub`` (user ID), ``email``, standard
        ``exp``/``iat`` claims, and a ``type`` claim to distinguish
        access and refresh tokens.

        No ``roles`` claim, though there was one. Nothing decided anything
        by it: the middleware reads the account from the database on every
        request, which is what makes a demotion take effect at once. What
        the claim did was look authoritative while being a snapshot up to
        fifteen minutes stale -- the shape a wrong decision arrives in
        later, when somebody reads roles off the token because they are
        there. Refresh tokens additionally carry a
        ``jti`` naming the session row that can retire them; access tokens
        carry a ``sid`` naming the login they belong to, which is what makes
        them revocable at all.

        Args:
            user: The authenticated user.
            expires_delta: Token lifetime.
            token_type: Either "access" or "refresh".
            token_id: Value for the ``jti`` claim, when the token is tracked.
            session_id: Value for the ``sid`` claim, naming the session chain.

        Returns:
            Encoded JWT string.
        """
        payload = {
            "sub": user.id,
            "email": user.email.value,
            "exp": datetime.now(timezone.utc) + expires_delta,
            "iat": datetime.now(timezone.utc),
            "type": token_type,
        }
        if token_id:
            payload["jti"] = token_id
        if session_id:
            payload["sid"] = session_id

        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def _create_access_token(self, user: User, session_id: str) -> str:
        """
        Generate a short-lived access token tied to a session.

        Args:
            user: Authenticated user.
            session_id: Chain the token belongs to.

        Returns:
            JWT access token string.
        """
        return self._create_token(
            user, self.access_expire, "access", session_id=session_id
        )

    def create_session_tokens(self, user: User) -> RefreshedTokens:
        """
        Open a session and issue the pair of tokens that belong to it.

        Both tokens are minted together so the access token can name the
        session it came from. Without that name it would be a bare signed
        claim that nothing can retire, and logging out would leave it usable
        until it expired on its own.

        Args:
            user: Authenticated user.

        Returns:
            The access and refresh tokens for the new session.
        """
        token_id = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + self.refresh_expire
        session = RefreshSession.create(
            user_id=user.id, token_id=token_id, expires_at=expires_at
        )

        with self.uow_factory() as uow:
            uow.refresh_sessions.save(session)
            uow.commit()

        return RefreshedTokens(
            access_token=self._create_access_token(user, session.chain_id),
            refresh_token=self._create_token(
                user, self.refresh_expire, "refresh", token_id=token_id
            ),
        )

    def revoke_refresh_token(self, refresh_token: str) -> bool:
        """
        End the login a refresh token belongs to, as logout does.

        The whole chain goes, not just the token presented: a login is one
        session however many times its token was rotated, and the access
        tokens issued along the way are tied to the chain. The user's other
        devices have their own chains and are untouched.

        Args:
            refresh_token: The refresh token to retire.

        Returns:
            True if a live session was found and revoked.
        """
        payload = self.validate_token(refresh_token, expected_type="refresh")
        if not payload:
            return False

        token_id = payload.get("jti")
        if not token_id:
            return False

        with self.uow_factory() as uow:
            session = uow.refresh_sessions.find_by_token_id(token_id)
            if not session or session.user_id != payload.get("sub"):
                return False

            # Conditional update rather than read-modify-write: writing back
            # a whole entity would overwrite columns another transaction had
            # just changed, so a concurrent rotation could erase the
            # revocation this call is making.
            revoked = uow.refresh_sessions.revoke_chain(session.chain_id)
            uow.commit()
            return revoked > 0

    def revoke_session_chain(self, chain_id: str) -> int:
        """
        End a login named by its session chain.

        Lets a client holding only an access token log out: the ``sid``
        claim names the chain, so no refresh token is needed.

        Args:
            chain_id: Chain to retire.

        Returns:
            Number of sessions revoked.
        """
        with self.uow_factory() as uow:
            revoked = uow.refresh_sessions.revoke_chain(chain_id)
            uow.commit()
            return revoked


    REQUIRED_CLAIMS = ("exp", "sub", "type")
    """Claims a token must carry before anything else is asked of it.

    PyJWT checks ``exp`` only when it is there. A token minted without one
    -- by this service in some future refactor, or by anyone who obtained
    the signing key -- was accepted and stayed valid forever, because there
    was nothing to compare the clock against. ``sub`` and ``type`` are
    demanded for a related reason: every caller here reads them, and absent
    they arrive as ``None``, which compares equal to nothing and quietly
    skips the checks built on them.
    """

    def validate_token(self, token: str, expected_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Decode and validate a JWT.

        A token missing any of ``REQUIRED_CLAIMS`` is rejected, so an
        expiry-less token cannot pass as a permanent one.

        Args:
            token: The JWT string.
            expected_type: If provided, the token's ``type`` claim must match.

        Returns:
            Dictionary with payload claims if valid, else None.
        """
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                options={"require": list(self.REQUIRED_CLAIMS)},
            )
            if expected_type and payload.get("type") != expected_type:
                return None
            return payload
        except jwt.PyJWTError:
            return None

    def refresh_access_token(self, refresh_token: str) -> Optional[RefreshedTokens]:
        """
        Exchange a refresh token for a fresh pair, rotating the refresh token.

        The presented token is retired and replaced. Presenting one that was
        already spent is treated as a replay -- the honest holder and the
        copy are indistinguishable at that point, so every session of the
        user is revoked and both have to log in again.

        Args:
            refresh_token: The refresh token.

        Returns:
            The new token pair, or None if the refresh token is invalid or
            already spent, the user no longer exists, or the account is
            deactivated.
        """
        payload = self.validate_token(token=refresh_token, expected_type="refresh")
        if not payload:
            return None

        user_id = payload.get("sub")
        token_id = payload.get("jti")
        if not user_id or not token_id:
            return None

        with self.uow_factory() as uow:
            session = uow.refresh_sessions.find_by_token_id(token_id)
            if not session:
                return None

            # The jti must belong to the subject that signed it. Without this
            # a token could name someone else's session and spend it.
            if session.user_id != user_id:
                return None

            if not session.is_usable():
                # Already rotated means this token was spent before and has
                # come back: it leaked. Retire its chain -- and only its
                # chain, so that holding one dead token is not a way to sign
                # the victim out of every other device they use.
                if session.replaced_by is not None:
                    uow.refresh_sessions.revoke_chain(session.chain_id)
                    uow.commit()
                return None

            user = uow.users.find_by_id(user_id)
            if not user or not user.is_active:
                return None

            new_token_id = str(uuid.uuid4())
            new_expires_at = datetime.now(timezone.utc) + self.refresh_expire

            # Claim the session before issuing anything. Checking usability
            # and then writing would let two concurrent requests both pass
            # the check and walk away with a live successor each.
            if not uow.refresh_sessions.claim_for_rotation(
                token_id, new_token_id
            ):
                return None

            uow.refresh_sessions.save(
                RefreshSession.create(
                    user_id=user.id,
                    token_id=new_token_id,
                    expires_at=new_expires_at,
                    chain_id=session.chain_id,
                )
            )
            uow.commit()

            return RefreshedTokens(
                access_token=self._create_access_token(user, session.chain_id),
                refresh_token=self._create_token(
                    user, self.refresh_expire, "refresh", token_id=new_token_id
                ),
            )
