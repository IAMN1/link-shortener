from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from link_shortener.domain import (Link, LinkRepository, OriginalUrl,
                                   ShortCode, UrlHash, LinkNotFoundError,
                                   OwnerID)
from link_shortener.infrastructure.database.models.link_model import LinkModel

class SQLAlchemyLinkRepository(LinkRepository):
    """
    SQLAlchemy-based persistence for Link aggregates.

    The repository receives a session at construction and uses it for all
    operations. It is the responsibility of the caller (usually a Unit of Work)
    to manage transactions and session lifecycle.
    """

    def __init__(self, session: Session):
        """
        Args:
            session: Active SQLAlchemy session bound to the current transaction.
        """
        self.session = session

    # ------------------------------------------------------------------
    # Save operations
    # ------------------------------------------------------------------
    def save(self, link: Link) -> Link:
        """Persist a new or updated Link entity.

        Args:
            link: Domain Link entity to save.

        Returns:
            The same Link instance (the entity is not mutated here; the ORM
            model is added to the session).
        """
        model = self._to_model(link)
        self.session.add(model)
        self.session.flush()
        return link

    def save_many(self, links: List[Link]) -> List[Link]:
        """Bulk persist multiple Link entities.

        Uses ``bulk_save_objects`` for performance; returned defaults are
        ignored because the domain objects are considered canonical.

        Args:
            links: List of Link domain entities.

        Returns:
            The same list of Links.
        """
        models = [self._to_model(link) for link in links]
        self.session.bulk_save_objects(models, return_defaults=False)
        self.session.flush()
        return links

    # ------------------------------------------------------------------
    # Single‑object lookups
    # ------------------------------------------------------------------
    def find_by_code(self, short_code: ShortCode) -> Optional[Link]:
        """Retrieve a Link by its short code.

        Args:
            short_code: ShortCode value object.

        Returns:
            Link entity if found, otherwise ``None``.
        """
        model = (
            self.session.query(LinkModel)
            .filter_by(short_code=short_code.value)
            .first()
        )
        return self._to_domain(model) if model else None

    def find_by_hash(self, url_hash: UrlHash) -> Optional[Link]:
        """Retrieve a Link by its URL hash (used for deduplication).

        Args:
            url_hash: UrlHash value object.

        Returns:
            Link entity if found, otherwise ``None``.
        """
        model = (
            self.session.query(LinkModel)
            .filter_by(url_hash=url_hash.value)
            .first()
        )
        return self._to_domain(model) if model else None

    # ------------------------------------------------------------------
    # Bulk lookups
    # ------------------------------------------------------------------
    def find_by_codes(
        self, short_codes: List[ShortCode]
    ) -> Dict[ShortCode, Optional[Link]]:
        """Bulk lookup by short codes.

        Queries the database once and builds a dictionary mapping every
        requested code to the found Link (or ``None`` if missing).

        Args:
            short_codes: List of ShortCode value objects.

        Returns:
            Dictionary where each input ShortCode is a key; value is the
            corresponding Link or ``None``.
        """
        code_values = [sc.value for sc in short_codes]
        models = (
            self.session.query(LinkModel)
            .filter(LinkModel.short_code.in_(code_values))
            .all()
        )
        result = {ShortCode(m.short_code): self._to_domain(m) for m in models}
        # Ensure every requested code is present in the dict (with None if absent)
        for code in short_codes:
            result.setdefault(code, None)
        return result

    def find_by_hashes(
        self, url_hashes: List[UrlHash]
    ) -> Dict[UrlHash, Optional[Link]]:
        """Bulk lookup by URL hashes.

        Args:
            url_hashes: List of UrlHash value objects.

        Returns:
            Dictionary mapping each UrlHash to the corresponding Link or ``None``.
        """
        hash_values = [h.value for h in url_hashes]
        models = (
            self.session.query(LinkModel)
            .filter(LinkModel.url_hash.in_(hash_values))
            .all()
        )
        result = {UrlHash(m.url_hash): self._to_domain(m) for m in models}
        for url_hash in url_hashes:
            result.setdefault(url_hash, None)
        return result

    # ------------------------------------------------------------------
    # Statistics & click updates
    # ------------------------------------------------------------------
    def increment_clicks(self, short_code: ShortCode) -> Link:
        """Atomically increment the click counter and update ``last_accessed``.

        After the update the latest state is freshly loaded from the database
        (``populate_existing``) to avoid stale session data.

        Args:
            short_code: ShortCode of the link to update.

        Returns:
            The updated Link entity.

        Raises:
            LinkNotFoundError: If no link with the given code exists.
        """
        # Atomic UPDATE in the database
        self.session.query(LinkModel).filter_by(
            short_code=short_code.value
        ).update(
            {
                LinkModel.clicks: LinkModel.clicks + 1,
                LinkModel.last_accessed: datetime.now(timezone.utc),
            },
            synchronize_session=False,
        )
        self.session.flush()

        # Force fresh read to get the updated values
        model = (
            self.session.query(LinkModel)
            .filter_by(short_code=short_code.value)
            .populate_existing()   # bypass session cache
            .first()
        )
        if not model:
            raise LinkNotFoundError(short_code.value)
        return self._to_domain(model)

    def increment_clicks_batch(self, short_codes: List[ShortCode]) -> None:
        """Bulk increment click counts for multiple links.

        Args:
            short_codes: List of ShortCode objects to update.
        """
        code_values = [sc.value for sc in short_codes]
        self.session.query(LinkModel).filter(
            LinkModel.short_code.in_(code_values)
        ).update(
            {
                LinkModel.clicks: LinkModel.clicks + 1,
                LinkModel.last_accessed: datetime.now(timezone.utc),
            },
            synchronize_session=False,
        )
        self.session.flush()

    def get_stats(self) -> dict:
        """Compute service-wide statistics.

        Returns:
            Dictionary with keys:
                - ``total_urls``: total number of short links.
                - ``total_clicks``: sum of all clicks.
                - ``popular_links``: up to 10 most-clicked Link entities.
        """
        total_urls = self.session.query(func.count(LinkModel.id)).scalar()
        total_clicks = self.session.query(func.sum(LinkModel.clicks)).scalar() or 0
        popular_links = (
            self.session.query(LinkModel)
            .order_by(LinkModel.clicks.desc())
            .limit(10)
            .all()
        )
        return {
            "total_urls": total_urls,
            "total_clicks": total_clicks,
            "popular_links": [self._to_domain(m) for m in popular_links],
        }

    # ------------------------------------------------------------------
    # Deletion & cleanup
    # ------------------------------------------------------------------
    def delete(self, short_code: ShortCode) -> bool:
        """Delete a link by its short code.

        Args:
            short_code: ShortCode of the link to delete.

        Returns:
            ``True`` if a link was deleted, ``False`` if no matching link existed.
        """
        model = self.session.query(LinkModel).filter_by(
            short_code=short_code.value
        ).first()
        if not model:
            return False
        self.session.delete(model)
        self.session.flush()
        return True

    def get_recent(self, limit: int = 10) -> List[Link]:
        """Return the most recently created links.

        Args:
            limit: Maximum number of links to return (default 10).

        Returns:
            List of Link entities ordered by ``created_at`` descending.
        """
        models = (
            self.session.query(LinkModel)
            .order_by(LinkModel.created_at.desc())
            .limit(limit)
            .all()
        )
        return [self._to_domain(m) for m in models]

    def delete_unaccessed_before(self, cutoff: datetime) -> List[ShortCode]:
        """Delete links that have not been accessed since a cutoff date.

        A link is considered unaccessed if:
            - ``last_accessed`` is before ``cutoff``, OR
            - ``last_accessed`` is NULL and ``created_at`` is before ``cutoff``.

        Args:
            cutoff: Timezone-aware UTC datetime threshold.

        Returns:
            List of ShortCode objects that were deleted.
        """
        models = self.session.query(LinkModel).filter(
            (LinkModel.last_accessed < cutoff)
            | ((LinkModel.last_accessed.is_(None)) & (LinkModel.created_at < cutoff))
        ).all()

        short_codes = [ShortCode(m.short_code) for m in models]
        if short_codes:
            self.session.query(LinkModel).filter(
                LinkModel.short_code.in_([sc.value for sc in short_codes])
            ).delete(synchronize_session=False)
        self.session.flush()
        return short_codes

    # ------------------------------------------------------------------
    # Domain <-> ORM conversion helpers
    # ------------------------------------------------------------------
    def _to_domain(self, model: LinkModel) -> Link:
        """
        Convert an ORM model to a domain Link entity.

        Ensures that ``created_at`` and ``last_accessed`` are timezone-aware
        (UTC). If they are naive, they are assumed to be UTC and converted.

        Args:
            model: The SQLAlchemy ``LinkModel`` instance.

        Returns:
            The corresponding domain ``Link`` entity.
        """
        created_at = model.created_at
        if created_at is not None and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        last_accessed = model.last_accessed
        if last_accessed is not None and last_accessed.tzinfo is None:
            last_accessed = last_accessed.replace(tzinfo=timezone.utc)

        return Link(
            id=model.id,
            url_hash=UrlHash(model.url_hash),
            short_code=ShortCode(model.short_code),
            original_url=OriginalUrl(model.original_url),
            created_at=created_at,
            clicks=model.clicks,
            last_accessed=last_accessed,
            owner=OwnerID(model.owner_id) if model.owner_id else None,
        )

    def _to_model(self, link: Link) -> LinkModel:
        """
        Convert a domain Link entity to an ORM model.

        The returned model is transient; it is not yet added to the session.

        Args:
            link: Domain Link entity.

        Returns:
            A new ``LinkModel`` instance.
        """
        return LinkModel(
            id=link.id,
            url_hash=link.url_hash.value,
            short_code=link.short_code.value,
            original_url=link.original_url.value,
            created_at=link.created_at,
            clicks=link.clicks,
            last_accessed=link.last_accessed,
            owner_id=link.owner.value if link.owner else None,
        )
