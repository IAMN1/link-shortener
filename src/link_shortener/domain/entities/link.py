import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ..value_objects.original_url import OriginalUrl
from ..value_objects.short_code import ShortCode
from ..value_objects.url_hash import UrlHash


@dataclass
class Link:
    """Доменная сущность ссылки c бизнес-логикой"""

    id: str
    url_hash: UrlHash
    short_code: ShortCode
    original_url: OriginalUrl
    created_at: datetime
    clicks: int = 0
    last_accessed: Optional[datetime] = None

    @classmethod
    def create(
        cls,
        url_hash: UrlHash,
        short_code: ShortCode,
        original_url: OriginalUrl,
        link_id: Optional[str] = None,
    ) -> "Link":
        """Фабричный метод для создания новой ссылки"""
        return cls(
            id=link_id or str(uuid.uuid4()),
            url_hash=url_hash,
            short_code=short_code,
            original_url=original_url,
            created_at=datetime.now(),
            clicks=0,
            last_accessed=None,
        )

    def increment_clicks(self) -> None:
        """
        Бизнес правило: увеличение счетчика переходов по ссылке
        """
        self.clicks += 1
        self.last_accessed = datetime.now()

    def is_popular(self, threshold: int = 100) -> bool:
        """Бизнес правило: является ли ссылка популярной"""
        return self.clicks > threshold

    def is_recent(self, days: int = 7) -> bool:
        """Бизнес правило: была ли ссылка создана недавно"""
        age = datetime.now() - self.created_at
        return age.days <= days

    def get_short_url(self, base_url: str) -> str:
        """Бизнес правило: формирования короткого URL"""
        return f"{base_url}/{self.short_code}"

    def __eq__(self, other: object) -> bool:
        """Проверка равенства ссылок (по ID)"""
        if not isinstance(other, Link):
            return False
        return self.id == other.id

    def __hash__(self) -> int:
        """Хэш для использования в множествах и словарях"""
        return hash(self.id)
