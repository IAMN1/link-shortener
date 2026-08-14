"""
How a migration decides which database to open.

``alembic`` is handed one string and reads nothing else of the
application's configuration, so this module produces that string without
demanding a configuration the application could start on -- secrets, the
domain and the mail settings would each otherwise stop a migration that
reads none of them.

Lives in ``src`` rather than in ``migrations/env.py`` so that it can be
tested: ``env.py`` is executed by alembic in a subprocess.
"""

import os
from typing import Optional

from sqlalchemy.engine import make_url

from link_shortener.infrastructure.configs.app.base import (
    BaseConfig, display_url, normalise_backend
)
from link_shortener.infrastructure.configs.app.env import is_unset, read_env_for
from link_shortener.infrastructure.configs.app.factory import ConfigFactory
from link_shortener.infrastructure.database.manager import (
    postgresql_connect_args
)


# ==========================================================================
# Caller handoff
# ==========================================================================
HANDOFF_ENV_VAR = "ALEMBIC_DATABASE_URL"
"""Variable through which a caller hands over the URL it already resolved.

The Flask CLI holds a live configuration when it shells out to alembic.
Without a handoff this module resolves one again from the subprocess's own
environment, and that environment does not carry the caller's profile:
nothing exports ``FLASK_ENV``, so a run under ``testing`` -- the profile
that pins an in-memory database precisely so a test cannot reach a real
one -- re-derived ``development`` from ``.env`` and landed on the
developer's own file.

The value travels in the environment rather than in ``-x``, alembic's
usual channel for caller-supplied values, because it carries the database
password and argv is visible in the process list.

It is also the one way past every check below, which is what makes it the
answer offered when a refusal is reported: a caller that names a database
outright has said what it wants, and there is nothing left to infer.
"""


def handed_over_url() -> Optional[str]:
    """
    Return the URL a caller handed over, if one did.

    Returns:
        The URL, stripped, or ``None`` when no caller supplied one.
    """
    handed_over = os.environ.get(HANDOFF_ENV_VAR)
    # Same blank-is-unset rule the configuration uses everywhere else: a
    # `${VAR}` that docker compose left empty must fall through rather than
    # be taken as a deliberate setting. Stripped as well, because a value
    # with a trailing newline is a *different* database -- one run created
    # a SQLite file whose name ended in "\n". ``get_database_url`` strips
    # its own side for the same reason, so the two agree.
    # ``handed_over is None`` is named alongside ``is_unset`` rather than
    # left to it: is_unset answers True for a blank string too, so it states
    # "not configured" without stating "not None", and the strip below needs
    # the second.
    if handed_over is None or is_unset(handed_over):
        return None

    # The ``postgres://`` alias is normalised on this path too, not only in
    # ``get_database_url``. This is the one way past every check below, so
    # a caller reaching for it is usually the operator whose hosting
    # provider printed that spelling in the first place, and alembic would
    # meet the same NoSuchModuleError the application does.
    return normalise_backend(handed_over.strip())


# ==========================================================================
# Policy
# ==========================================================================
PROFILES_ALLOWED_A_DEFAULT_DATABASE = ("development",)
"""Profiles that may migrate a SQLite database no ``DATABASE_URL`` named.

Everywhere else that database is a mistake with no symptom.
``DATABASE_TYPE`` defaults to ``sqlite`` and ``DATABASE_NAME`` to
``db_shortener``, so a deployment that configured neither gets a migration
that succeeds against a brand-new empty file in the project root, and a
service that then starts on it and answers as if the data had never
existed. Refusing costs an operator who genuinely wants SQLite one
explicit ``DATABASE_URL``; not refusing costs the other one their data.

The profile has to have been *named* for this to apply, which is not the
same as being resolved: ``DEFAULT_ENV`` is ``development`` too, so a host
that sets no ``FLASK_ENV`` anywhere would otherwise have the guard
switched off by the very omission it is looking for.

This guards the bare command only. ``flask alembic ...`` hands over the
URL the running application is configured with, and a caller that already
knows its database is not the case being caught -- it also prints that
database, which the bare path now does as well.
"""


def resolve_database_url(env: Optional[str] = None) -> str:
    """
    Return the URL of the database a migration should run against.

    Args:
        env: Explicit profile name, or ``None`` to resolve it the way the
            application does.

    Returns:
        SQLAlchemy-compatible database URL.

    Raises:
        ValueError: If the database settings cannot produce a usable URL,
            or the result is one a migration should not be run against.
    """
    handed_over = handed_over_url()
    if handed_over is not None:
        return handed_over

    # Standalone use -- `alembic upgrade head` straight from a shell has no
    # caller to inherit from, so the profile is selected and the `.env`
    # files are applied exactly as they are for the application. Only the
    # checks that do not describe the database are left out.
    named = ConfigFactory.named_env(env)
    profile = ConfigFactory.resolve_env(named)
    config = ConfigFactory.create_config_unvalidated(profile)

    # DATABASE_NAME and DATABASE_TYPE describe how a URL is assembled from
    # parts, and ``get_database_url`` does not read either once
    # ``DATABASE_URL`` is set. Checking them anyway meant a stale
    # ``DATABASE_TYPE`` refused a migration whose database was named in
    # full, on the recovery path this exists to keep open, with a message
    # naming a setting that changes nothing.
    if not config.DATABASE_URL:
        config.validate_database()

    url = config.get_database_url()
    _refuse_a_database_a_migration_should_not_touch(profile, named, config, url)
    _refuse_a_database_nobody_named(profile, config)

    return url


def migration_connect_args(url: str) -> dict:
    """
    Return the driver arguments a migration should connect with.

    The migration builds its own engine from the ``[alembic]`` section,
    which holds nothing but the URL, so without this it would wait on an
    unreachable server far longer than the application does -- with the
    application waiting on it, since the stack starts the two in order.

    Read from ``BaseConfig`` rather than from the selected profile, since
    a handed-over URL comes with no profile at all. No profile overrides
    either setting, so the values are the same ones the application
    connects under.

    Args:
        url: URL the migration is about to open.

    Returns:
        Mapping for ``create_engine(connect_args=...)``; empty for SQLite,
        which has neither a server nor a socket to bound.
    """
    if make_url(url).get_backend_name() != "postgresql":
        return {}

    return postgresql_connect_args(
        BaseConfig.DATABASE_CONNECT_TIMEOUT,
        BaseConfig.DATABASE_STATEMENT_TIMEOUT,
    )


def _refuse_a_database_nobody_named(profile: str, config: BaseConfig) -> None:
    """
    Refuse the PostgreSQL equivalent of the default SQLite file.

    ``DATABASE_HOST`` defaults to ``localhost`` and ``DATABASE_NAME`` to
    ``db_shortener``, so a deployed profile that set only
    ``DATABASE_TYPE=postgresql`` and a user builds a perfectly valid URL
    to a server and a database nobody chose. The application refuses that
    -- ``staging`` and ``production`` demand both parts explicitly -- and
    a migration that succeeds against the wrong database is worse than
    one that refuses.

    Args:
        profile: Resolved profile name.
        config: Configuration the URL was built from.

    Raises:
        ValueError: If a deployed profile left either part at its default.
    """
    if profile in PROFILES_ALLOWED_A_DEFAULT_DATABASE:
        return

    if config.DATABASE_URL or config.DATABASE_TYPE != "postgresql":
        return

    for name in ("DATABASE_HOST", "DATABASE_NAME"):
        default = vars(BaseConfig)[name].default
        if getattr(config, name) == default and is_unset(
            read_env_for(config, name)
        ):
            raise ValueError(
                f"the {profile!r} profile would migrate a database nobody "
                f"named: {name} is still {default!r}, its built-in default. "
                f"Name it, or give the whole connection URL in DATABASE_URL."
            )


def _refuse_a_database_a_migration_should_not_touch(
    profile: str, named: Optional[str], config: BaseConfig, url: str
) -> None:
    """
    Refuse the two SQLite outcomes that report success and change nothing.

    One is a database nobody named, which is a new empty file the defaults
    fall back to -- reported differently depending on whether the profile
    was named, because an unnamed profile is the likelier mistake and has
    its own answer. The other is an in-memory database, which is not a
    file at all: the schema is built and thrown away when the process
    ends. ``alembic`` says ``Running upgrade -> 0001`` in both cases, on a
    path whose whole job is to change a database that outlives it.

    Args:
        profile: Resolved profile name.
        named: Profile somebody actually named, or ``None``.
        config: Configuration the URL was built from.
        url: URL the configuration produced.

    Raises:
        ValueError: If the URL is one of those two.
    """
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite":
        return

    if named is not None and profile in PROFILES_ALLOWED_A_DEFAULT_DATABASE:
        return

    remedy = (
        "Point DATABASE_TYPE and the DATABASE_* parts at the real server, "
        "or name the SQLite file in DATABASE_URL, which is the only way to "
        "ask for one under this profile."
    )
    if config.IGNORE_ENV:
        # Telling a detached profile to set DATABASE_URL would be advice
        # that cannot work: it reads no configuration from the environment,
        # so following it produces the same refusal a second time.
        remedy = (
            "This profile takes no configuration from the environment, so "
            f"only {HANDOFF_ENV_VAR} can send the migration elsewhere."
        )

    database = parsed.database or ""
    if not database or ":memory:" in database:
        raise ValueError(
            f"the {profile!r} profile would migrate {display_url(url)}, a "
            "database that exists only inside this process: the schema "
            "would be built and dropped again when the command exits, and "
            f"the command would report success. {remedy}"
        )

    # Asked of the configuration rather than of ``os.environ``, so that a
    # profile detached by IGNORE_ENV is not talked out of the refusal by a
    # variable it does not read: under ``testing`` an exported
    # ``DATABASE_URL`` is not what the profile connects with.
    if not is_unset(read_env_for(config, "DATABASE_URL")):
        return

    if named is None:
        raise ValueError(
            "nothing names a profile -- no FLASK_ENV in the environment and "
            f"none in .env -- so this fell back to {profile!r} and to "
            f"{display_url(url)}, the SQLite default. Name the profile in "
            "FLASK_ENV, or the database in DATABASE_URL."
        )

    raise ValueError(
        f"the {profile!r} profile would migrate {display_url(url)}, a SQLite "
        f"database that no DATABASE_URL in the environment named. {remedy}"
    )
