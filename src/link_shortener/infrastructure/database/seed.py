"""
Database seeding utilities.

The primary entry point is ``seed_base_roles`` which loads the standard
RBAC configuration from a YAML file idempotently.
"""

from pathlib import Path
from sqlalchemy.orm import Session

from link_shortener.infrastructure.database.role_loader import (
    LoadSummary, RoleLoader
)


# Path to the default RBAC configuration file.
# Resolves to: src/link_shortener/infrastructure/configs/rbac/roles.yaml
DEFAULT_RBAC_CONFIG_PATH = (
    Path(__file__).parent.parent / "configs" / "rbac" / "roles.yaml"
)

def seed_base_roles(session: Session) -> LoadSummary:
    """
    Ensure the standard system roles and permissions exist in the database.

    The function loads the RBAC configuration from the default YAML file
    and creates any missing records without modifying existing ones -- an
    existing role keeps both its fields and its permissions, so an edit made
    through the admin API survives.

    This is safe to call multiple times. It is used by:
    * Application startup (when ``AUTO_SEED_ROLES=True``)
    * The CLI command ``flask db load-base-roles``

    Not by any Alembic migration: no revision calls it, and a deployment
    that skips this step comes up with an empty ``roles`` table and
    answers 401 to anonymous shortening.

    Args:
        session: An active database session.

    Returns:
        What the pass did, including the roles it deliberately left alone.

    Raises:
        FileNotFoundError: If the default YAML configuration file is missing.
    """

    if not DEFAULT_RBAC_CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"RBAC configuration file not found at {DEFAULT_RBAC_CONFIG_PATH}. "
            "Please ensure the file exists before running this command."
        )
    
    loader = RoleLoader(session)
    # We do not update existing records to avoid overwriting manual changes.
    return loader.load_from_yaml(
        DEFAULT_RBAC_CONFIG_PATH, update_existing=False
    )
