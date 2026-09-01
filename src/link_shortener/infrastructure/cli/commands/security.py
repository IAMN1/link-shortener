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
            # The two claims that say which login this token belongs to.
            # Not printed -- they are opaque ids and answer no question an
            # operator asks -- but the caller needs them to ask whether the
            # service would still accept the token, which is a different
            # question from whether it stands up on its own.
            "sid": claims.get("sid"),
            "jti": claims.get("jti"),
        }
    except Exception as e:
        return {
            "valid": False,
            "error": str(e),
        }


# What a rewrite of each name costs the deployment. Used to word the
# refusal, because the four are not alike: replacing SECRET_KEY
# invalidates what was handed out, while replacing a service password
# leaves the service itself still expecting the old one.
#
# SHORT_CODE_PEPPER used to be listed with SECRET_KEY, as stopping "the
# codes already handed out from resolving". It does not. The pepper is
# read in one place -- Base64UrlCodeGenerator.generate -- and a link is
# resolved by looking its stored code up in the table, with no code
# recomputed anywhere. Measured: a code made under one pepper answered
# 302 to the right destination from a process running another, and the
# same URL offered again under the second pepper still deduplicated to
# the first link, because deduplication reads the URL and not the code.
# The sentence mattered because it read as "rotating this revokes the
# links you handed out", which is a thing this service cannot do.
_COST_OF_REPLACING = {
    "SECRET_KEY": "signs out every session and voids every issued token",
    "SHORT_CODE_PEPPER": (
        "changes the code a URL not yet shortened will get; links already "
        "made keep theirs and go on resolving"
    ),
    "DATABASE_PASSWORD": (
        "leaves the database still expecting the old one -- the volume "
        "keeps the password it was initialised with"
    ),
    "REDIS_PASSWORD": "leaves both Redis still expecting the old one",
}

# The passwords the stack's own services are started with. Kept apart from
# the two above because they answer a different question: those are secrets
# the application signs with, these are credentials for containers that this
# deployment happens to run. A local run on SQLite with the cache in memory
# needs neither, which is why filling them in is asked for rather than
# assumed.
SERVICE_PASSWORD_NAMES = ("DATABASE_PASSWORD", "REDIS_PASSWORD")


def generate_secrets(with_service_passwords: bool = False) -> dict[str, str]:
    """Generate new secure random values for the deployment's secrets.

    Args:
        with_service_passwords: Also generate ``DATABASE_PASSWORD`` and
            ``REDIS_PASSWORD``, the credentials the stack's own PostgreSQL
            and Redis are started with. Off by default: a local run has
            neither service, and writing passwords for containers that do
            not exist would put two more values in a file to keep secret
            for nothing.

    Returns:
        The values, keyed by the variable each belongs in.
    """
    fresh = {
        "SECRET_KEY": secrets.token_hex(32),
        "SHORT_CODE_PEPPER": secrets.token_hex(32),
    }
    if with_service_passwords:
        # url-safe rather than hex: these travel inside DATABASE_URL and
        # REDIS_URL, where a character needing percent-encoding turns a
        # working password into an unparseable address.
        for name in SERVICE_PASSWORD_NAMES:
            fresh[name] = secrets.token_urlsafe(24)
    return fresh


def write_secrets(
    path: Path,
    force: bool = False,
    with_service_passwords: bool = False,
) -> dict[str, str]:
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
        with_service_passwords: Also fill ``DATABASE_PASSWORD`` and
            ``REDIS_PASSWORD`` -- what the Docker stack's own PostgreSQL and
            Redis are started with, and what they refuse to start without.

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
    fresh = generate_secrets(with_service_passwords=with_service_passwords)

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
            # The consequence is named per value rather than in one
            # sentence about the two application secrets: with service
            # passwords in the set, a blanket "it signs out every session"
            # would be wrong about half of what is listed, and a refusal
            # that misdescribes the damage is one an operator overrides
            # without reading.
            costs = "; ".join(
                f"{name} -- {_COST_OF_REPLACING[name]}" for name in taken
            )
            raise ValueError(
                f"{path} already sets {', '.join(taken)}. "
                f"Pass --force to replace, knowing that {costs}."
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


SECRET_FLOOR_BYTES = 32
"""The shortest key this service will call configured.

RFC 7518 section 3.2, on ``HS256``: "A key of the same size as the hash
output (for instance, 256 bits for ``HS256``) or larger MUST be used with
this algorithm." PyJWT says the same thing out loud -- it warns
``InsecureKeyLengthWarning: The HMAC key is 16 bytes long, which is below
the minimum recommended length of 32 bytes for SHA256`` -- and that
warning goes to a log nobody reads at deployment time.

``generate-secrets`` already writes 64 hex characters, which is exactly
this. The floor is here so that a key typed by hand is measured against
the same standard.
"""


def _state_of(value: Optional[str]) -> str:
    """
    Whether one secret is missing, too short, or fit to use.

    Takes the value rather than the name it is read under, so that the
    two reads below stay literal: ``test_every_setting_has_its_line``
    sweeps the source for ``os.environ.get("NAME")`` and holds each key
    against the template, and a read whose key comes from a variable is
    one it cannot answer for.

    Length in bytes rather than characters: the key is encoded before it
    is signed with, and a 32-character key of two-byte characters is not
    a 32-byte key.

    Args:
        value: What the environment holds, or ``None``.

    Returns:
        ``"MISSING"``, ``"WEAK"`` or ``"OK"``.
    """
    if not value:
        return "MISSING"
    if len(value.encode("utf-8")) < SECRET_FLOOR_BYTES:
        return "WEAK"
    return "OK"


def check_secrets() -> dict[str, str]:
    """Check that the required secrets are configured, and worth having.

    It used to answer ``bool`` -- set or unset -- so ``SECRET_KEY=abc``
    came back ``OK`` with exit 0. Measured on a live stack: three
    characters passed a command whose whole purpose is to be the gate a
    deployment runs before it starts. What the key is worth is not a
    separate question from whether it is there: an attacker who can guess
    it forges every token this service issues.

    Returns:
        ``"MISSING"``, ``"WEAK"`` or ``"OK"`` for each required variable.
        Read from the environment rather than from the configuration,
        because that is where a deployment sets them and where this
        command is asked whether it did.
    """
    return {
        "SECRET_KEY": _state_of(os.environ.get("SECRET_KEY")),
        "SHORT_CODE_PEPPER": _state_of(os.environ.get("SHORT_CODE_PEPPER")),
    }


def list_users(uow_factory: UnitOfWorkFactory) -> list[dict]:
    """List all users with their roles.

    Args:
        uow_factory: Factory for Unit of Work instances.

    Returns:
        One dict per account, with ``id``, ``email``, ``is_active``,
        ``email_verified`` and ``roles``. Flattened here rather than
        handed over as entities, because the caller prints a fixed table
        of exactly these and the value objects would each need unwrapping
        at the format string.

        ``email_verified`` is here because the table read as though
        ``Active`` answered "can this account be used", and it does not:
        measured, an account with ``is_active=t, email_verified=f`` was
        printed ``True`` and answered ``401`` at sign-in. The command
        beside this one, ``maintenance clean-unverified``, deletes
        accounts by exactly the column the listing did not show.
    """
    with uow_factory() as uow:
        users = uow.users.list_all()
        return [
            {
                "id": str(user.id),
                "email": user.email.value,
                "is_active": user.is_active,
                "email_verified": user.email_verified,
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
