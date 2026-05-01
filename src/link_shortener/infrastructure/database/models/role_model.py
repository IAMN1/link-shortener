import uuid
from typing import List, Optional

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from link_shortener.infrastructure.database.models.base import Base
from link_shortener.infrastructure.database.models.user_model import UserModel
from link_shortener.infrastructure.database.models.permission_model import PermissionModel
from link_shortener.infrastructure.database.models.associations import(
    role_permission_table, user_role_table
)


class RoleModel(Base):
    """
    ORM model for a named role.

    Has many-to-many relationships to UserModel and PermissionModel.
    """
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
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
