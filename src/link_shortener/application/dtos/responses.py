from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from link_shortener.domain import Link


@dataclass
class ShortLinkResponse:
    """
    DTO для ответа при создании сокращенной ссылки
    """

    short_code: str
    short_url: str
    original_url: str
    clicks: int
    created_at: datetime
    last_accessed: Optional[datetime]
    is_new: bool = False
    from_cache: bool = False

    @classmethod
    def from_link(
        cls, link: Link, base_url: str, is_new: bool = False, from_cache: bool = False
    ) -> "ShortLinkResponse":
        """Фабричный метод для создания DTO из доменной сущности"""

        short_url = f'{base_url.rstrip("/")}/{link.short_code.value}'

        return cls(
            short_code=str(link.short_code.value),
            short_url=short_url,
            original_url=str(link.original_url.value),
            clicks=link.clicks,
            created_at=link.created_at,
            last_accessed=link.last_accessed,
            is_new=is_new,
            from_cache=from_cache,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь для сериализации"""
        return {
            "short_code": self.short_code,
            "short_url": self.short_url,
            "original_url": self.original_url,
            "clicks": self.clicks,
            "created_at": self.created_at.isoformat(),
            "last_accessed": (
                self.last_accessed.isoformat() if self.last_accessed else None
            ),
            "is_new": self.is_new,
            "from_cache": self.from_cache,
        }


@dataclass
class BatchItemResponse:
    """DTO для одного элемента пакетной обработки"""

    success: bool
    url: str
    short_code: Optional[str] = None
    original_url: Optional[str] = None
    short_url: str
    clicks: int = 0
    error: Optional[str] = None
    is_new: bool = False
    from_cache: bool = False
    duplicate_of: Optional[str] = None
    processing_time_ms: Optional[float] = None

    @classmethod
    def success_(
        cls,
        url: str,
        short_code: str,
        original_url: str,
        base_url: str,
        clicks: int = 0,
        is_new: bool = False,
        from_cache: bool = False,
        duplicate_of: Optional[str] = None,
    ) -> "BatchItemResponse":
        """Фабричный метод для успешного результата"""
        short_url = f'{base_url.rstrip("/")}/{short_code}'
        return cls(
            url=url,
            success=True,
            short_code=short_code,
            original_url=original_url,
            short_url=short_url,
            clicks=clicks,
            is_new=is_new,
            from_cache=from_cache,
            duplicate_of=duplicate_of,
        )

    @classmethod
    def error_(cls, url: str, error: str) -> "BatchItemResponse":
        """Фабричный метод для ошибки"""
        return cls(success=False, url=url, error=error)


@dataclass
class BatchCreateResponse:
    """DTO для ответа пакетного создания ссылок"""

    items: List[BatchItemResponse]
    total: int = 0
    successful: int = 0
    failed: int = 0
    from_cache_count: int = 0
    from_db_count: int = 0
    new_count: int = 0
    processing_time_seconds: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)

    @classmethod
    def from_results(cls, results: List[BatchItemResponse]) -> "BatchCreateResponse":
        total = len(results)
        successful = sum(1 for r in results if r.success)
        failed = total - successful
        from_cache_count = sum(1 for r in results if r.from_cache)
        from_db_count = sum(
            1 for r in results if r.success and not r.is_new and not r.from_cache
        )
        new_count = sum(1 for r in results if r.is_new)

        return cls(
            items=results,
            total=total,
            successful=successful,
            failed=failed,
            from_cache_count=from_cache_count,
            from_db_count=from_db_count,
            new_count=new_count,
            created_at=datetime.now(),
        )

    @classmethod
    def empty(cls) -> "BatchCreateResponse":
        return cls(items=[])


@dataclass
class StatsItemResponse:
    """DTO для элемента статистики"""

    short_code: str
    short_url: str
    original_url: str
    clicks: int
    created_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь"""
        return {
            "short_code": self.short_code,
            "short_url": self.short_url,
            "original_url": self.original_url,
            "clicks": self.clicks,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class ServiceStatsResponse:
    """DTO для статистики сервиса"""

    total_urls: int
    total_clicks: int
    avg_clicks_per_url: float
    popular_links: List[StatsItemResponse]

    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь"""
        return {
            "total_urls": self.total_urls,
            "total_clicks": self.total_clicks,
            "avg_clicks_per_url": round(self.avg_clicks_per_url, 2),
            "popular_links": [link.to_dict() for link in self.popular_links],
        }


@dataclass
class ExtendedLinkInfoResponse:
    """DTO Для расширенной информации о ссылке"""

    short_code: str
    short_url: str
    original_url: str
    clicks: int
    created_at: datetime
    last_accessed: Optional[datetime]
    is_popular: bool
    is_recent: bool
    age_days: int
    clicks_per_day: float
    last_access_days_ago: Optional[int]

    @classmethod
    def from_link(cls, link: Link, base_url: str) -> "ExtendedLinkInfoResponse":
        """конвертация из ссылки в DTO"""

        short_url = f'{base_url.rstrip("/")}/{link.short_code.value}'

        age_days = (datetime.now() - link.created_at).days
        clicks_per_day = (
            round(link.clicks / max(age_days, 1), 2) if link.clicks > 0 else 0.0
        )
        last_access_days_ago = (
            (datetime.now() - link.last_accessed).days if link.last_accessed else None
        )

        return cls(
            short_code=str(link.short_code.value),
            short_url=short_url,
            original_url=str(link.original_url.value),
            clicks=link.clicks,
            created_at=link.created_at,
            last_accessed=link.last_accessed,
            is_popular=link.is_popular(),
            is_recent=link.is_recent(),
            age_days=age_days,
            clicks_per_day=clicks_per_day,
            last_access_days_ago=last_access_days_ago,
        )
