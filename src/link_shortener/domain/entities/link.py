from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class Link:
    """Доменная сущность ссылки"""
    id: str
    url_hash: str
    short_code: str
    original_url: str
    created_at: datetime
    clicks: int = 0
    last_accessed: Optional[datetime] = None

    def increment_clicks(self) -> None:
        """
        Бизнес правило: увеличение счетчика переходов по ссылке
        """
        self.clicks += 1
        self.last_accessed = datetime.now()
    

