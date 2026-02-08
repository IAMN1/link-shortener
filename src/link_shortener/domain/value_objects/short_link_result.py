"""
Value Objects для результатов операций с сылками
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..entities.link import Link


@dataclass(frozen=True)
class ShortLinkCreationResult:
    """Value object для результата создания ссылки"""

    link: Link
    is_new: bool
    from_cache: bool


@dataclass(frozen=True)
class RedirectResult:
    """Value objext для результата редиректа"""

    original_url: str
    from_cache: bool = False
    clicks: Optional[int] = None


@dataclass(frozen=True)
class LinkInfoResult:
    """Value object для информации о ссылки"""

    id: str
    url_hash: str
    short_code: str
    original_url: str
    clicks: int
    created_at: str
    last_accessed: Optional[str] = None


@dataclass
class BatchLinkData:
    """Вспомогательная структура для пакетной обработки"""

    url: str
    url_hash: Optional[str] = None
    short_code: Optional[str] = None
    clicks: Optional[int] = None


@dataclass(frozen=True)
class BatchResultItem:
    """Value object для элемента результата пакетной обработки"""

    success: bool
    data: BatchLinkData
    error: Optional[str] = None
    is_new: Optional[bool] = None
    from_cache: bool = False


@dataclass(frozen=True)
class BatchProcessingSummary:
    """Value object для сводки пакетной обработки"""

    total: int
    successful: int
    failed: int
    new: int
    existing: int
    from_cache: int


@dataclass
class ServiceStatsResult:
    """Value object для статистикик сервиса"""

    total_urls: int
    total_clicks: int
    avg_clicks_per_url: float
    popular_urls: List[Dict[str, Any]]
