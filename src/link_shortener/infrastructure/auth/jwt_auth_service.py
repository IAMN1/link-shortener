from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional
import bcrypt
import jwt

from link_shortener.application import AuthenticationService, UnitOfWork
from link_shortener.domain import User, Email


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
        uow_factory: Callable[[], UnitOfWork],
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
    
    def hash_password(self, plain: str) -> str:
        """
        Hash a plain-text password using bcrypt.

        Args:
            plain: Raw password.

        Returns:
            Hashed password string.
        """
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password=plain.encode(), salt=salt).decode()
    
    def verify_password(self, plain: str, hashed: str) -> bool:
        """
        Compare a plain-text password against a bcrypt hash.

        Args:
            plain: Raw password.
            hashed: Stored hash.

        Returns:
            True if they match.
        """
        return bcrypt.checkpw(password=plain.encode(), hashed_password=hashed.encode())
    
    def authenticate(self, email: str, password: str) -> Optional[User]:
        """
        Authenticate a user by email and password.

        Args:
            email: User email.
            password: Raw password.

        Returns:
            User entity if credentials are valid, else None.
        """
        with self.uow_factory(read_only=True) as uow:
            user = uow.users.find_by_email(Email(email))
            if not user:
                return None
            if not self.verify_password(password, user.password_hash.value):
                return None
            # Возвращаем detached-сущность (сессия закроется)
            return user
    
    def _create_token(self, user: User, expires_delta: timedelta) -> str:
        """
        Internal helper to build a signed JWT.

        The payload includes ``sub`` (user ID), ``email``, ``roles``, and
        standard ``exp``/``iat`` claims.

        Args:
            user: The authenticated user.
            expires_delta: Token lifetime.

        Returns:
            Encoded JWT string.
        """
        payload = {
            "sub": user.id,
            "email": user.email.value,
            "roles": [role.name for role in user.roles],
            "exp": datetime.now(timezone.utc) + expires_delta,
            "iat": datetime.now(timezone.utc),
        }
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
    
    def create_access_token(self, user: User) -> str:
        """
        Generate a short-lived access token.

        Args:
            user: Authenticated user.

        Returns:
            JWT access token string.
        """
        return self._create_token(user, self.access_expire)
    
    def create_refresh_token(self, user: User) -> str:
        """
        Generate a long-lived refresh token.

        Args:
            user: Authenticated user.

        Returns:
            JWT refresh token string.
        """
        return self._create_token(user, self.refresh_expire)
    
    def validate_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Decode and validate a JWT.

        Args:
            token: The JWT string.

        Returns:
            Dictionary with payload claims if valid, else None.
        """
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return payload
        except jwt.PyJWTError:
            return None
    
    def refresh_access_token(self, refresh_token: str) -> Optional[str]:
        """
        Issue a new access token using a valid refresh token.

        Args:
            refresh_token: The refresh token.

        Returns:
            New access token string, or None if refresh token is invalid
            or the user no longer exists.
        """
        payload = self.validate_token(token=refresh_token)
        if not payload:
            return None
        
        user_id = payload.get("sub")
        if not user_id:
            return None
        
        with self.uow_factory(read_only=True) as uow:
            user = uow.users.find_by_id(user_id)
            if not user:
                return None
            
            return self.create_access_token(user)
