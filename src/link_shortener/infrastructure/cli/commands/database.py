from pathlib import Path
from typing import Optional

from sqlalchemy import text

from link_shortener.application import RequestContext, SeedDatabaseUseCase
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.use_cases.admin.database.seed_database import SeedResult
from link_shortener.infrastructure.cli.commands.alembic import AlembicCommands
from link_shortener.infrastructure.cli.commands.maintenance import (
    what_the_database_said,
)
from link_shortener.infrastructure.database.models.base import Base
from link_shortener.infrastructure.database.manager import DatabaseManager
from link_shortener.infrastructure.database.models.role_model import RoleModel
from link_shortener.infrastructure.database.role_loader import RoleLoader
from link_shortener.infrastructure.database.seed import seed_base_roles


def init_db(db_manager: DatabaseManager, use_alembic: bool) -> str:
    """
    Create all database tables based on SQLAlchemy models.
    This command is only allowed when USE_ALEMBIC is False.

    Args:
        db_manager: DatabaseManager instance.
        use_alembic: flag indicating whether the alembic is used or not

    Returns:
        The line to report, for the adapter to print.
    """
    if use_alembic is True:
        raise RuntimeError(
            "USE_ALEMBIC is enabled. Please use 'alembic upgrade head' to manage schema."
        )
    db_manager.create_tables()
    return "Database tables created successfully!"

def drop_db(db_manager: DatabaseManager, use_alembic: bool) -> str:
    """
    Drop all database tables (destructive).
    This command is only allowed when USE_ALEMBIC is False.

    The confirmation is the caller's. It used to be asked twice -- the
    adapter put the question to the operator, and a ``confirm`` flag here
    refused a second time -- so this module held a branch that printed
    "Use confirm=True to drop all tables.", advice in the vocabulary of a
    Python API, on a path no operator could reach and no caller passed.

    Args:
        db_manager: DatabaseManager instance.
        use_alembic: flag indicating whether the alembic is used or not

    Returns:
        The line to report, for the adapter to print.
    """
    if use_alembic is True:
        raise RuntimeError(
            "USE_ALEMBIC is enabled. Please use 'alembic downgrade base' to reset schema."
        )

    # The same check ``create_tables`` makes on the other side of this pair:
    # the engine is built by ``connect()``, and dropping through ``None``
    # otherwise fails with a message naming neither the manager nor the
    # missing call.
    if db_manager.engine is None:
        raise RuntimeError("Database not connected. Call connect() first.")

    Base.metadata.drop_all(bind=db_manager.engine)
    return "All tables dropped successfully!"

def seed_db(use_case: SeedDatabaseUseCase, count: int, context: RequestContext) -> SeedResult:
    """
    Fill database with test links using SeedDatabaseUseCase.

    Args:
        use_case: SeedDatabaseUseCase instance.
        count: Number of test links to create.
        context: Request context.

    Returns:
        SeedResult with the created / already-existing counts.
    """
    return use_case.execute(count, context)

def load_base_roles_from_cfg(db_manager: DatabaseManager) -> str:
    """
    Seed the database with default roles and permissions from the standard YAML config.
    This function is idempotent and safe to run multiple times.

    Returns:
        The line to report, for the adapter to print.
    """
    with db_manager.session() as session:
        summary = seed_base_roles(session)
    # Reported rather than merely done: seeding leaves existing roles alone,
    # so "seeded successfully" was equally true for a pass that created the
    # whole of RBAC and for one that changed nothing at all -- including
    # when the operator had just edited the YAML.
    return f"Roles and permissions seeded. {summary.describe()}"

def load_custom_roles_from_cfg(
    db_manager: DatabaseManager,
    file_path: str,
    audit: AuditLogger,
    update_existing: bool = False,
) -> str:
    """
    Load roles and permissions from a YAML file, and record the new roles.

    Each role this creates is written to the audit journal, as
    ``CreateRoleUseCase`` writes the one created through the API. A role
    is a set of entitlements and creating one hands them out, which is
    the rule the vocabulary admits events by -- and this door recorded
    nothing, so an operator could add a role carrying
    ``admin:manage_users`` and the journal would hold no trace of where
    it came from.

    ``db load-base-roles`` beside it deliberately writes nothing: seeding
    the database is excluded by that same rule, being the installation
    putting its own four roles in place rather than somebody granting
    anything. This command is the other thing -- an operator bringing a
    file of their own.

    A role whose permissions ``--update-existing`` replaces is recorded
    too, as ``UpdateRolePermissionsUseCase`` records the same act on the
    HTTP path. It is the widest-reaching change in the vocabulary: every
    account wearing the role is moved at once, without any of their
    accounts being touched, so an investigator asking why an account
    could suddenly do something finds nothing against the account and has
    to find it here. Measured before this existed: one command took
    ``probe:read`` off a role and gave it ``admin:manage_users``, and the
    journal held nothing at all.

    Args:
        db_manager: DatabaseManager instance.
        file_path: Path to the YAML file.
        audit: Where the new roles are recorded, already carrying the
            command's context.
        update_existing: If True, update existing permissions/roles; otherwise only create new ones.

    Returns:
        The lines to report, for the adapter to print.
    """
    with db_manager.session() as session:
        loader = RoleLoader(session)
        summary = loader.load_from_yaml(
            Path(file_path), update_existing=update_existing
        )
        # Push the new rows out before querying for them. Sessions here
        # are built with ``autoflush=False`` -- the loader says so itself,
        # about the very same trap one step earlier -- so without this the
        # query below sees none of the roles just created and every record
        # goes out claiming the role grants nothing.
        session.flush()

        # Read back inside the session that made them, so the record says
        # what each role actually carries rather than what the file asked
        # for -- a permission named twice, or one the loader resolved to
        # an existing row, would otherwise be reported wrongly.
        granted = {
            role.name: [permission.name for permission in role.permissions]
            for role in session.query(RoleModel).filter(
                RoleModel.name.in_(summary.roles_created)
            )
        } if summary.roles_created else {}

        # How far a regrant reached, counted while the session is open.
        # A count rather than a list, the shape the audit port asks for:
        # it is what says whether the change moved nobody or everybody.
        holders = {
            role.name: len(role.users)
            for role in session.query(RoleModel).filter(
                RoleModel.name.in_(
                    [r.name for r in summary.roles_regranted]
                )
            )
        } if summary.roles_regranted else {}

    for name in summary.roles_created:
        audit.log_role_created(role=name, permissions=granted.get(name, []))

    for regranted in summary.roles_regranted:
        audit.log_role_permissions_changed(
            role=regranted.name,
            permissions_before=regranted.permissions_before,
            permissions_after=regranted.permissions_after,
            holders=holders.get(regranted.name, 0),
        )

    action = "Updated" if update_existing else "Loaded"
    return (
        f"{action} roles and permissions from {file_path}\n"
        f"{summary.describe()}"
    )


def check_db_connection(db_manager: DatabaseManager) -> Optional[str]:
    """
    Verify that the database is reachable, and say why if it is not.

    The reason travels back rather than being swallowed: "Database
    connection failed." on its own does not tell a wrong password from an
    unreachable host, a wrong database name or a timeout -- on the one
    command whose whole job is to diagnose.

    Only the first line of the reason travels, like everywhere else that
    hands a database error to a person: the rest carries the statement
    and its parameters.

    Args:
        db_manager: DatabaseManager instance.

    Returns:
        ``None`` when a simple SELECT 1 succeeds, otherwise the first
        line of whatever the database or the driver said.
    """
    try:
        with db_manager.session() as session:
            if session.execute(text("SELECT 1")).scalar() == 1:
                return None
            return "the database did not answer SELECT 1 with 1"
    except Exception as error:
        return what_the_database_said(error)

def migrate_db(
    use_alembic: bool,
    database_url: Optional[str] = None,
) -> tuple[bool, str]:
    """
    Apply database migrations using Alembic.

    Delegates to ``AlembicCommands`` rather than launching alembic itself,
    so the caller's database URL reaches the subprocess. A copy that built
    its own would migrate whatever database the ambient environment named.

    Neither prints nor exits. It did both -- the only function in this
    layer that decided what an operator sees and what the shell reads --
    which is why ``db migrate`` was also the only command in the adapter
    with no error handling of its own: there was nothing left for it to
    handle.

    Args:
        use_alembic: flag indicating whether alembic is enabled
        database_url: Database to migrate. Handed to alembic so the schema
            change lands where the application actually looks.

    Returns:
        Tuple of (success, output), in the shape ``AlembicCommands``
        answers in.
    """
    if not use_alembic:
        return True, "Alembic is disabled. Use 'flask db init' to create tables."

    return AlembicCommands.upgrade("head", database_url=database_url)
