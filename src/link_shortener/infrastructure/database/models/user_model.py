import uuid
from datetime import datetime, timezone
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from link_shortener.infrastructure.database.models.base import Base
from link_shortener.infrastructure.database.models.associations import user_role_table

if TYPE_CHECKING:
    from link_shortener.infrastructure.database.models.role_model import RoleModel

class UserModel(Base):
    """
    ORM model representing a registered user.

    Many-to-many to roles via ``user_role_table``.
    """
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    """Whether the address was proven readable by whoever registered it.

    The server default is False, so a row inserted by anything other than
    this application -- a fixture, a repair script, a future migration --
    is unconfirmed rather than trusted. The accounts that predate this
    column are confirmed by the migration itself, once, because nobody was
    ever going to mail them a link.
    """
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Many-to-many to RoleModel
    roles: Mapped[List["RoleModel"]] = relationship(
        "RoleModel",
        secondary=user_role_table,
        back_populates="users",
        lazy="selectin",
    )

    # One-to-many to LinkModel (optional).
    # links: Mapped[List["LinkModel"]] = relationship(back_populates="owner")
