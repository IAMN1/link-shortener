from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class UrlEvent:
    """Базовое событие для ссылки"""
    timestamp: datetime
    original_url: str
    short_code: str
    user_ip: Optional[str] = None
    user_agent: Optional[str] = None

@dataclass(frozen=True)
class UrlCreated(UrlEvent):
    """Событие создания ссылки"""
    url_hash: str
    is_new: bool = True

@dataclass(frozen=True)
class UrlAccessed(UrlEvent):
    """Событие доступа к ссылке"""
    from_cache: bool = False
    current_clicks: Optional[int] = None