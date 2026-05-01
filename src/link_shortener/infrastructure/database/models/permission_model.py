import uuid
from typing import List, Optional

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from link_shortener.infrastructure.database.models.base import Base
from link_shortener.infrastructure.database.models.role_model import RoleModel
from link_shortener.infrastructure.database.models.associations import role_permission_table


class PermissionModel(Base):
    """
    ORM model for a single permission (e.g., 'link:create').

    Linked to roles via a many-to-many association table.
    """
    __tablename__ = "permissions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    resource: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)

    # Many-to-many to RoleModel
    roles: Mapped[List["RoleModel"]] = relationship(
        "RoleModel",
        secondary=role_permission_table,
        back_populates="permissions",
    )
