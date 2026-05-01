from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from link_shortener.application.utils.url_utils import build_short_url


@dataclass
class BatchItemResponse:
    """
    Result for a single URL inside a batch operation.

    Attributes:
        success: True if the URL was processed without errors.
        url: The original URL that was requested.
        short_code: The generated short code (if success).
        original_url: The canonical original URL (may differ if deduplicated).
        short_url: Full short link (including base URL).
        clicks: Existing click count (0 for new links).
        error: Error message if processing failed.
        is_new: True if a new link was created.
        from_cache: True if the link was retrieved from cache.
        duplicate_of: If this URL is a duplicate, the canonical original URL.
        processing_time_ms: Time taken to process this single URL (optional).
    """
    success: bool
    url: str
    short_code: Optional[str] = None
    original_url: Optional[str] = None
    short_url: Optional[str] = None
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
        """
        Factory for a successful response item.

        Args:
            url: Original input URL.
            short_code: The generated or found short code.
            original_url: Canonical original URL.
            base_url: Base URL of the service (to build the short link).
            clicks: Current click count.
            is_new: Whether this link was just created.
            from_cache: Whether it came from cache.
            duplicate_of: Canonical URL if this is a duplicate.

        Returns:
            BatchItemResponse with success=True.
        """
        short_url = build_short_url(base_url, short_code)
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
        """
        Factory for a failed response item.

        Args:
            url: The input URL that caused the error.
            error: Human-readable error description.

        Returns:
            BatchItemResponse with success=False.
        """
        return cls(success=False, url=url, error=error, short_url=None)


@dataclass
class BatchCreateResponse:
    """
    Aggregated results of a batch link creation request.

    Attributes:
        items: Per-URL results.
        total: Total number of URLs processed.
        successful: Number of successful creations/cache hits.
        failed: Number of failed URLs.
        from_cache_count: Items found in cache.
        from_db_count: Items fetched from DB (not new, not cache).
        new_count: Newly created links.
        processing_time_seconds: Total execution time of the batch.
        created_at: Timestamp of the batch completion.
    """
    items: List[BatchItemResponse]
    total: int = 0
    successful: int = 0
    failed: int = 0
    from_cache_count: int = 0
    from_db_count: int = 0
    new_count: int = 0
    processing_time_seconds: float = 0.0
    created_at: datetime = field(default_factory=datetime.now(timezone.utc))

    @classmethod
    def from_results(cls, results: List[BatchItemResponse]) -> "BatchCreateResponse":
        """
        Build aggregated response from a flat list of item results.

        Args:
            results: List of BatchItemResponse objects.

        Returns:
            BatchCreateResponse with computed aggregates.
        """
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
            created_at=datetime.now(timezone.utc),
        )

    @classmethod
    def empty(cls) -> "BatchCreateResponse":
        """
        Create an empty response for zero URLs.

        Returns:
            BatchCreateResponse with all counts zero.
        """
        return cls(items=[])
