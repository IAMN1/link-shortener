from datetime import datetime
from sqlalchemy import Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base

class TableURL(Base):
    """
    Модель для хранения сокращенных ссылок
    
    Vars:
        original_url (str): Оригинальная ссылка
        url_hash (str): Хэш URL
        short_code (str): Сгенерированная короткая ссылка
        clicks (int): Количество переходов по ссылке
    """
    __tablename__ = 'urls'

    id: Mapped[int] = mapped_column(primary_key=True)
    original_url: Mapped[str] = mapped_column(
        String(2048), 
        nullable=False,
        index=True
    )
    url_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True
    )
    short_code: Mapped[str] = mapped_column(
        String(10), unique=True, 
        index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        default=datetime.now, 
        server_default=func.now()
    )
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    last_accessed: Mapped[datetime] = mapped_column(
        default=datetime.now,
        server_default=func.now()
    )


# TODO для будущего расширения функционала
# class BlockedURL(Base):
#     """Таблица с заблокированными вредоносными URL"""
#     __tablename__ = 'Blocked_urls'
#     pass
