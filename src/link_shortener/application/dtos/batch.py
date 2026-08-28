from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from link_shortener.application.dtos.refusal import Refusal
from link_shortener.application.utils.url_utils import build_short_url


MAX_BATCH_ITEMS = 100
"""Hard ceiling on how many URLs one request may carry.

The request schema refuses a longer list before anything looks at it, so a
body cannot be turned into unbounded work. ``BATCH_CREATE_LIMIT`` is the
policy inside that ceiling and cannot be set past it: above it, the setting
silently did nothing, because the schema refused the request first and with
its own message.

Here rather than in the configuration, for the reason ``HARD_LIMIT`` is on
the journal's port: the number arrives from a request, and whoever takes
the request has to refuse an excess before any work starts. Read out of
``infrastructure.configs``, it was the web layer importing a fact from a
layer it is not allowed to know -- the same fault the journal schema was
already tested against, left standing here because the batch is a slice of
its own.

Beside the DTOs of the operation it bounds: they are what the boundary
already reads out of this layer, and the size a batch may be is part of
the same contract as the shape it comes back in.
"""


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
        error: Why this item was refused, carried rather than worded: a
            sentence finished here cannot be translated at the boundary.
        is_new: True if a new link was created.
        from_cache: True if the link was retrieved from cache.
        duplicate_of: If this URL is a duplicate, the canonical original URL.
        expires_at: When the link expires; ``None`` for a permanent one.
        link_id: Identifier of the stored row. Internal: the web layer signs
            it into the deletion token handed to a guest, and never puts it
            in a response.
    """
    success: bool
    url: str
    short_code: Optional[str] = None
    original_url: Optional[str] = None
    short_url: Optional[str] = None
    clicks: int = 0
    # Batch is where a guest silently gets a seven-day link, so withholding
    # the expiry here is exactly where it misleads most.
    expires_at: Optional[datetime] = None
    error: Optional[Refusal] = None
    is_new: bool = False
    from_cache: bool = False
    duplicate_of: Optional[str] = None
    link_id: Optional[str] = None

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
        expires_at: Optional[datetime] = None,
        link_id: Optional[str] = None,
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
            expires_at: When the link expires; ``None`` for a permanent one.
            link_id: Identifier of the stored row, for the deletion token.

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
            expires_at=expires_at,
            link_id=link_id,
        )

    @classmethod
    def error_(cls, url: str, error: Refusal) -> "BatchItemResponse":
        """
        Factory for a failed response item.

        Args:
            url: The input URL that caused the error.
            error: The refusal, with its code and its msgid intact.

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
        from_db_count: Items a repository lookup found.
        new_count: Newly created links.
        processing_time_seconds: How long the batch took, in seconds.
        created_at: Timestamp of the batch completion.

    The three source counts do not have to add up to ``successful``.
    A batch may name one address more than once, and the repeats come
    back pointing at the link the first one got -- they are that link
    again, not a fourth place it was found. Counted as repository hits,
    which is what ``not is_new and not from_cache`` amounts to, they
    reported lookups nobody made: three copies of one new URL answered
    ``new_count=1, from_db_count=2`` against a batch that read the
    repository for one hash and found nothing.
    """
    items: List[BatchItemResponse]
    total: int = 0
    successful: int = 0
    failed: int = 0
    from_cache_count: int = 0
    from_db_count: int = 0
    new_count: int = 0
    processing_time_seconds: float = 0.0
    # A factory, not a timestamp: the field held ``datetime.now(...)`` --
    # already a datetime -- so anything that fell back to the default
    # raised "'datetime.datetime' object is not callable". An empty batch
    # did exactly that and came back a 500.
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @classmethod
    def from_results(
        cls,
        results: List[BatchItemResponse],
        processing_time_seconds: float = 0.0,
    ) -> "BatchCreateResponse":
        """
        Build aggregated response from a flat list of item results.

        Args:
            results: List of BatchItemResponse objects.
            processing_time_seconds: How long the batch took. Taken as an
                argument because this is the only way the field is ever
                filled: the use case measured the duration, wrote it to the
                journal and built the response without it, so the field
                documented as the batch's execution time was ``0.0`` in
                every response the service has ever produced.

        Returns:
            BatchCreateResponse with computed aggregates.
        """
        total = len(results)
        successful = sum(1 for r in results if r.success)
        failed = total - successful
        from_cache_count = sum(1 for r in results if r.from_cache)
        from_db_count = sum(
            1 for r in results
            if r.success
            and not r.is_new
            and not r.from_cache
            and not r.duplicate_of
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
            processing_time_seconds=processing_time_seconds,
            created_at=datetime.now(timezone.utc),
        )
