import uuid
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from link_shortener.domain.policies.role_policy import (
    ROLE_DESCRIPTION_MAX_LENGTH, ROLE_NAME_MAX_LENGTH,
)
from link_shortener.infrastructure.database.models.base import Base
from link_shortener.infrastructure.database.models.associations import(
    role_permission_table, user_role_table
)
if TYPE_CHECKING:
    from .user_model import UserModel
    from .permission_model import PermissionModel


class RoleModel(Base):
    """
    ORM model for a named role.

    Has many-to-many relationships to UserModel and PermissionModel.
    """
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # The request schema bounds the name by this same constant, so a name
    # the schema accepts fits what `create_all` builds here. The width a
    # migrated database has is a third literal, in
    # `migrations/versions/0001_initial_schema.py`; a test reads it back
    # against the constant, because this model only serves SQLite in tests.
    name: Mapped[str] = mapped_column(
        String(ROLE_NAME_MAX_LENGTH), unique=True, nullable=False
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(ROLE_DESCRIPTION_MAX_LENGTH), nullable=True
    )
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    # Many-to-many to UserModel
    users: Mapped[List["UserModel"]] = relationship(
        "UserModel",
        secondary=user_role_table,
        back_populates="roles",
    )
    # Many-to-many to PermissionModel
    permissions: Mapped[List["PermissionModel"]] = relationship(
        "PermissionModel",
        secondary=role_permission_table,
        back_populates="roles",
        lazy="selectin",
    )
