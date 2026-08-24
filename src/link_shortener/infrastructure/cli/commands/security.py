import secrets
import os
from pathlib import Path
from typing import Optional

from link_shortener.application import UnitOfWorkFactory
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.auth.auth_service import (
    AuthenticationService,
)
from link_shortener.application.services.user_management_service import (
    UserManagementService,
)
from link_shortener.domain import Email


def validate_token(
    auth_service: AuthenticationService,
    token: str
) -> dict:
    """Validate a JWT token and return its claims.

    What the token carries, not what the account holds: the two are not
    the same thing, and the token no longer states the roles at all.
    ``flask security list-users`` answers that question from the database,
    which is where every authorization decision reads it from.

    Args:
        auth_service: The service that reads and verifies the token.
        token: The token as it was typed.

    Returns:
        ``{"valid": False, "error": <why>}`` for a token that does not
        stand up, and otherwise ``{"valid": True}`` with ``user_id``,
        ``email``, ``type`` and ``exp`` off the claims. A refused token is
        an answer rather than an exception: this command exists to say
        what is wrong with a token, so failing at it is its ordinary work.
    """
    try:
        claims = auth_service.validate_token(token)
        if not claims:
            # validate_token returns None for an invalid or expired token
            # instead of raising, so this case has to be handled explicitly.
            return {
                "valid": False,
                "error": "Token is invalid or expired",
            }
        return {
            "valid": True,
            # The user id lives in the standard "sub" claim, not "user_id" -
            # see JwtAuthenticationService._create_token.
            "user_id": claims.get("sub"),
            "email": claims.get("email"),
            "type": claims.get("type"),
            "exp": claims.get("exp"),
        }
    except Exception as e:
        return {
            "valid": False,
            "error": str(e),
        }


def generate_secrets() -> dict[str, str]:
    """Generate new secure random values for SECRET_KEY and SHORT_CODE_PEPPER.

    Returns:
        Both values, keyed by the variable each belongs in.
    """
    return {
        "SECRET_KEY": secrets.token_hex(32),
        "SHORT_CODE_PEPPER": secrets.token_hex(32),
    }


def write_secrets(path: Path, force: bool = False) -> dict[str, str]:
    """
    Put freshly generated secrets into an env file, in place.

    The printed form of this command asks the reader to copy two lines
    into a file by hand, which is the one step in the guide that cannot
    be pasted into a shell. Everything around it is a command, so the
    setup broke in the middle for the sake of two values nobody chooses.

    Existing values are kept unless ``force`` says otherwise: rewriting a
    ``SECRET_KEY`` signs out every session and voids every issued token,
    and rewriting ``SHORT_CODE_PEPPER`` is worse -- codes already handed
    out stop resolving. Neither is something a setup command may do
    because a file happened to be there.

    Args:
        path: Env file to edit. It has to exist already; this command
            fills a template in rather than inventing one.
        force: Replace values that are already set.

    Returns:
        The values written, keyed by variable name.

    Raises:
        FileNotFoundError: When ``path`` is not there, or is not a file.
        OSError: When the file cannot be read or written -- a ``.env``
            owned by root is the ordinary way this happens.
        ValueError: When a value is already set and ``force`` is false.
    """
    if not path.is_file():
        # Two different things, said apart: a path that is not there at
        # all, and one that is there and is not a file. "does not exist"
        # was printed for a directory, which is a sentence an operator
        # can act on only by disbelieving it.
        if path.exists():
            raise FileNotFoundError(f"{path} is not a file")
        raise FileNotFoundError(f"{path} does not exist")

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    fresh = generate_secrets()

    # What each name already holds, and on which line. A name absent from
    # the file is absent from here too, and gets appended below.
    seen: dict[str, int] = {}
    for number, line in enumerate(lines):
        name = line.split("=", 1)[0].strip() if "=" in line else ""
        if name in fresh and name not in seen:
            seen[name] = number

    if not force:
        taken = sorted(
            name for name, number in seen.items()
            if lines[number].split("=", 1)[1].strip()
        )
        if taken:
            raise ValueError(
                f"{path} already sets {', '.join(taken)}. "
                "Pass --force to replace, knowing it signs out every "
                "session and, for SHORT_CODE_PEPPER, breaks the codes "
                "already handed out."
            )

    for name, value in fresh.items():
        if name in seen:
            # The trailing newline is taken from the line being replaced,
            # so a file that ends without one keeps ending without one.
            ending = "\n" if lines[seen[name]].endswith("\n") else ""
            lines[seen[name]] = f"{name}={value}{ending}"
        else:
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += "\n"
            lines.append(f"{name}={value}\n")

    path.write_text("".join(lines), encoding="utf-8")
    return fresh


def check_secrets() -> dict[str, bool]:
    """Check if required secrets are configured in environment.

    Returns:
        Whether each required variable holds anything, keyed by name.
        Read from the environment rather than from the configuration,
        because that is where a deployment sets them and where this
        command is asked whether it did.
    """
    return {
        "SECRET_KEY": bool(os.environ.get("SECRET_KEY")),
        "SHORT_CODE_PEPPER": bool(os.environ.get("SHORT_CODE_PEPPER")),
    }


def list_users(uow_factory: UnitOfWorkFactory) -> list[dict]:
    """List all users with their roles.

    Args:
        uow_factory: Factory for Unit of Work instances.

    Returns:
        One dict per account, with ``id``, ``email``, ``is_active`` and
        ``roles``. Flattened here rather than handed over as entities,
        because the caller prints a fixed table of exactly these four and
        the value objects would each need unwrapping at the format string.
    """
    with uow_factory() as uow:
        users = uow.users.list_all()
        return [
            {
                "id": str(user.id),
                "email": user.email.value,
                "is_active": user.is_active,
                "roles": [role.name for role in user.roles],
            }
            for user in users
        ]


def list_roles(uow_factory: UnitOfWorkFactory) -> list[dict]:
    """List all roles with their permissions.

    Args:
        uow_factory: Factory for Unit of Work instances.

    Returns:
        One dict per role, with ``id``, ``name``, ``description`` and
        ``permissions``, for the reason ``list_users`` gives.
    """
    with uow_factory() as uow:
        roles = uow.roles.list_all()
        return [
            {
                "id": str(role.id),
                "name": role.name,
                "description": role.description,
                "permissions": [perm.name for perm in role.permissions],
            }
            for role in roles
        ]


def reset_password(
    uow_factory: UnitOfWorkFactory,
    user_service: UserManagementService,
    audit: AuditLogger,
    email: str,
    new_password: str,
) -> Optional[int]:
    """Reset a user's password, closing what the old one held, on the record.

    The sessions and the mailed links go with it, in
    ``update_password``. That is the rule for every password change in
    the service, and this path is the one it is most needed on: an
    operator runs this command for an account somebody else may be in.

    The record is written here for the same reason the sessions are
    closed there: this is the operator's path, reached for an account
    believed to be compromised, and it was the one of the three ways a
    password changes that left no trace. The other two are recorded in
    their use cases -- ``PASSWORD_CHANGED`` and ``PASSWORD_RESET`` -- so
    an account whose password an operator replaced showed a hash that
    changed at a time nothing in the journal accounts for.

    Written after the commit, not inside it: a journal that cannot be
    written is not a reason to leave the account with its old password,
    and the audit adapters already degrade quietly rather than raise.

    Args:
        uow_factory: Factory for Unit of Work instances.
        user_service: The service that applies the change.
        audit: Where the change is recorded, already carrying the
            command's context.
        email: Address of the account.
        new_password: The password to set.

    Returns:
        How many sessions were closed, or ``None`` if no such account.
        Zero is a real answer -- an account nobody was signed in to --
        and is why this is not a boolean.
    """
    with uow_factory() as uow:
        user = uow.users.find_by_email(Email(email))
        if not user:
            return None
        revoked = user_service.update_password(uow, user, new_password)
        uow.commit()
        user_id = user.id

    audit.log_user_password_reset(
        target_user_id=user_id, sessions_revoked=revoked
    )
    return revoked
