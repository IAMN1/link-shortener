import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context


from link_shortener.infrastructure.database.models.base import Base
from link_shortener.infrastructure.configs.app.base import display_url
from link_shortener.infrastructure.configs.app.migration_url import (
    HANDOFF_ENV_VAR, handed_over_url, migration_connect_args,
    resolve_database_url
)


# ==========================================================================
# Database URL
# ==========================================================================
try:
    database_url = resolve_database_url()
except ValueError as error:
    # Reported rather than raised. A migration is one of the ways out of a
    # misconfigured deployment, so the operator standing in front of a
    # refusal needs the way past it -- and a traceback ending inside the
    # configuration factory reads as a bug in the tool rather than as an
    # answer about their settings.
    raise SystemExit(
        f"alembic: {error}\n\n"
        "To migrate a named database without building the application "
        f"configuration at all, set {HANDOFF_ENV_VAR} to its URL."
    )

# Say which database this is about to change, the way `flask alembic` does
# -- and only when nobody else already has, so the two do not both print
# it. Without this the bare command was silent about its target, and a
# forgotten ALEMBIC_DATABASE_URL left over from an earlier command sent the
# migration to that database instead, reporting the same success either
# way. On stderr, where alembic's own account of what it did already goes.
if handed_over_url() is None:
    print(f"Database: {display_url(database_url)}", file=sys.stderr)


# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config


# Set the URL from our own application, overwriting whatever alembic.ini says.
#
# `%` is doubled: the value passes through ConfigParser with interpolation,
# and a raw percent sign in a password brought the command down with
# "invalid interpolation syntax", printing the password in clear text in the
# error message. Worse, `%(name)s` did not fail at all -- it was quietly
# substituted, and the caller's URL was replaced on the way through.
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    # `connect_args` are supplied here because the section this engine is
    # built from holds nothing but the URL: the bounds the application
    # connects under live in its configuration and never reached a
    # migration. Unbounded, an unreachable server held this command for
    # over a minute -- and `app` waits for it to finish before it starts.
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=migration_connect_args(database_url),
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
