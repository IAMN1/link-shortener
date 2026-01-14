from datetime import datetime
from sqlalchemy import Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base

class ShortURL(Base):
    """Модель для хранения сокращенных ссылок"""
    __tablename__ = 'shorturls'

    id: Mapped[int] = mapped_column(primary_key=True)
    original_url: Mapped[str] = mapped_column(
        String(2048), 
        nullable=False
    )
    short_code: Mapped[str] = mapped_column(
        String(10), unique=True, 
        index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        default=datetime.now, 
        server_default=func.now()
    )
    clicks: Mapped[int] = mapped_column(Integer, default=0)


# TODO для будущего расширения функционала
# class BlockedURL(Base):
#     """Таблица с заблокированными вредоносными URL"""
#     __tablename__ = 'Blocked_urls'
#     pass
