import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from link_shortener.domain.value_objects.original_url import OriginalUrl
from link_shortener.domain.value_objects.owner_id import OwnerID
from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.domain.value_objects.url_hash import UrlHash


@dataclass
class Link:
    """
    Domain entity representing a shortened link with business logic.

    Attributes:
        id: Unique identifier (UUID string).
        url_hash: Hash of the original URL (for deduplication).
        short_code: Generated short code.
        original_url: Original URL value object.
        created_at: Timestamp when the link was created.
        clicks: Number of times the link has been accessed.
        last_accessed: Timestamp of the last access (if any).
        owner: Owner of the link (value object, None for guests).
    """

    id: str
    url_hash: UrlHash
    short_code: ShortCode
    original_url: OriginalUrl
    created_at: datetime
    clicks: int = 0
    last_accessed: Optional[datetime] = None
    owner: Optional[OwnerID] = None

    @classmethod
    def create(
        cls,
        url_hash: UrlHash,
        short_code: ShortCode,
        original_url: OriginalUrl,
        link_id: Optional[str] = None,
        owner: Optional[OwnerID] = None
    ) -> "Link":
        """
        Factory method to create a new Link instance.

        Args:
            url_hash: Hash of the original URL (for deduplication).
            short_code: Generated short code.
            original_url: Original URL value object.
            link_id: Optional UUID; if not provided, a new one is generated.
            owner: Optional OwnerID value object representing the link owner.

        Returns:
            A new Link instance with default values (clicks=0, created_at=now).
        """
        return cls(
            id=link_id if link_id is not None else str(uuid.uuid4()),
            url_hash=url_hash,
            short_code=short_code,
            original_url=original_url,
            created_at=datetime.now(timezone.utc),
            clicks=0,
            last_accessed=None,
            owner=owner or OwnerID(None)
        )

    def increment_clicks(self) -> None:
        """
        Business rule: increment the click counter and update last_accessed to now.
        """
        self.clicks += 1
        self.last_accessed = datetime.now(timezone.utc)

    def is_popular(self, threshold: int) -> bool:
        """
        Business rule: determine if the link is popular based on click threshold.

        Args:
            threshold: Minimum number of clicks to be considered popular.

        Returns:
            True if clicks > threshold, else False.
        """
        return self.clicks > threshold

    def is_recent(self, days: int) -> bool:
        """
        Business rule: check if the link was created within the given number of days.

        Args:
            days: Number of days to consider as "recent".

        Returns:
            True if created_at is within the last `days` days, else False.
        """
        age = datetime.now(timezone.utc) - self.created_at
        return age.days <= days

    def __eq__(self, other: object) -> bool:
        """Equality check based on link ID."""
        if not isinstance(other, Link):
            return False
        return self.id == other.id

    def __hash__(self) -> int:
        """Hash based on link ID (enables use in sets/dictionaries)."""
        return hash(self.id)
