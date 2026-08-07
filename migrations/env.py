import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context


from link_shortener.infrastructure.database.models.base import Base
from link_shortener.infrastructure.configs.app.env import is_unset
from link_shortener.infrastructure.configs.app.factory import get_config


# ==========================================================================
# Database URL
# ==========================================================================
HANDOFF_ENV_VAR = "ALEMBIC_DATABASE_URL"
"""Variable through which a caller hands over the URL it already resolved.

The Flask CLI holds a live configuration when it shells out to alembic.
Without a handoff this file called ``get_config()`` again, and the
subprocess rebuilt the configuration from whatever the ambient environment
happened to say -- not necessarily the profile the application runs under.
The ``testing`` profile is the sharp case: it sets ``IGNORE_ENV`` and pins
an in-memory SQLite database precisely so that a test run cannot reach a
real one, and a re-derived configuration walked straight past that.

The value travels in the environment rather than in ``-x``, alembic's usual
channel for caller-supplied values, because it carries the database
password and argv is visible in the process list.
"""


def _resolve_database_url() -> str:
    """
    Return the URL handed over by the caller, or derive one.

    Returns:
        SQLAlchemy-compatible database URL.
    """
    handed_over = os.environ.get(HANDOFF_ENV_VAR)
    # Same blank-is-unset rule the configuration uses everywhere else: a
    # `${VAR}` that docker compose left empty must fall through rather than
    # be taken as a deliberate setting. Stripped as well, because a value
    # with a trailing newline is a *different* database -- one run created
    # a SQLite file whose name ended in "\n".
    if not is_unset(handed_over):
        return handed_over.strip()

    # Standalone use -- `alembic upgrade head` straight from a shell has no
    # caller to inherit from, so the configuration is built the usual way.
    return get_config().get_database_url()


database_url = _resolve_database_url()


# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config


# Устанавливаем URL из нашего приложения (перезаписываем то, что в alembic.ini)
#
# `%` удваивается: значение проходит через ConfigParser с интерполяцией, и
# сырой процент в пароле ронял команду с "invalid interpolation syntax",
# показывая пароль открытым текстом в сообщении об ошибке. Хуже того,
# `%(name)s` не падал, а молча подставлялся — и URL вызывающей стороны
# оказывался подменён по дороге.
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
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
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
