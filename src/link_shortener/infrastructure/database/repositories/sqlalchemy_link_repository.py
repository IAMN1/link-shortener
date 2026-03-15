from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import func

from link_shortener.domain import (Link, LinkRepository, OriginalUrl,
                                   ShortCode, UrlHash)
from link_shortener.infrastructure.database.models import LinkModel
from link_shortener.infrastructure.database.manager import DatabaseManager

class SQLAlchemyLinkRepository(LinkRepository):
    """
    SQLAlchemy implementation of the LinkRepository interface.

    Converts between domain Link entities and database LinkModel objects.
    Uses DatabaseManager for session handling.
    """

    def __init__(self, db_manager: DatabaseManager):
        """
        Initialize the repository.

        Args:
            db_manager: DatabaseManager instance that provides sessions.
        """
        self.db_manager = db_manager

    def save(self, link: Link) -> Link:
        """Save a single link to the database."""

        with self.db_manager.session() as session:
            link_model = LinkModel(
                id=link.id,
                url_hash=link.url_hash.value,
                short_code=link.short_code.value,
                original_url=link.original_url.value,
                created_at=link.created_at,
                clicks=link.clicks,
                last_accessed=link.last_accessed,
            )

            session.add(link_model)
            session.flush()

            return self._to_domain(link_model)

    def save_many(self, links: List[Link]) -> List[Link]:
        """Bulk save multiple links."""

        with self.db_manager.session() as session:
            link_models = []
            for link in links:
                link_model = LinkModel(
                    id=link.id,
                    url_hash=link.url_hash.value,
                    short_code=link.short_code.value,
                    original_url=link.original_url.value,
                    created_at=link.created_at,
                    clicks=link.clicks,
                    last_accessed=link.last_accessed,
                )
                link_models.append(link_model)

            session.bulk_save_objects(link_models, return_defaults=False)
            session.flush()

            return links

    def find_by_code(self, short_code: ShortCode) -> Optional[Link]:
        """Find a link by its short code."""

        with self.db_manager.session() as session:
            link_model = (
                session.query(LinkModel)
                .filter_by(short_code=short_code.value)
                .first()
            )
            return self._to_domain(link_model) if link_model else None

    def find_by_codes(
        self, short_codes: List[ShortCode]
    ) -> Dict[ShortCode, Optional[Link]]:
        """Bulk find links by multiple short codes."""

        with self.db_manager.session() as session:
            code_values = [sc.value for sc in short_codes]
            link_models = (
                session.query(LinkModel)
                .filter(LinkModel.short_code.in_(code_values))
                .all()
            )

            # Build result dict
            result = {
                ShortCode(model.short_code): self._to_domain(model) 
                for model in link_models
            }

            # Ensure all requested codes are present
            # (with None if not found)
            for code in short_codes:
                result.setdefault(code, None)

            return result

    def find_by_hash(self, url_hash: UrlHash) -> Optional[Link]:
        """Find a link by its URL hash."""

        with self.db_manager.session() as session:
            link_model = (
                session.query(LinkModel)
                .filter_by(url_hash=url_hash.value)
                .first()
            )

            return self._to_domain(link_model) if link_model else None

    def find_by_hashes(
        self, url_hashes: List[UrlHash]
    ) -> Dict[UrlHash, Optional[Link]]:
        """Bulk find links by multiple URL hashes."""

        with self.db_manager.session() as session:
            hash_values = [h.value for h in url_hashes]
            link_models = (
                session.query(LinkModel)
                .filter(LinkModel.url_hash.in_(hash_values))
                .all()
            )

            # преобразование в словарь для быстрого поиска
            result = {
                UrlHash(model.url_hash): self._to_domain(model) 
                for model in link_models
            }

            # Добавление None для ненайденных хэшей
            for url_hash in url_hashes:
                result.setdefault(url_hash, None)

            return result

    def increment_clicks(self, short_code: ShortCode) -> None:
        """Increment click count for a given short code."""

        with self.db_manager.session() as session:
            session.query(LinkModel).filter_by(
                short_code=short_code.value
            ).update(
                {
                    LinkModel.clicks: LinkModel.clicks + 1,
                    LinkModel.last_accessed: datetime.now(timezone.utc),
                },
                synchronize_session=False,
            )

    def increment_clicks_batch(self, short_codes: List[ShortCode]) -> None:
        """Bulk increment click counts for multiple short codes."""

        with self.db_manager.session() as session:
            code_values = [sc.value for sc in short_codes]

            # Bulk_update для эффективности
            session.query(LinkModel).filter(
                LinkModel.short_code.in_(code_values)
            ).update(
                {
                    LinkModel.clicks: LinkModel.clicks + 1,
                    LinkModel.last_accessed: datetime.now(timezone.utc),
                },
                synchronize_session=False,
            )

    def get_stats(self) -> dict:
        """
        Retrieve service statistics: 
            - total URLs, 
            - total clicks, 
            - top 10 popular links.
        """

        with self.db_manager.session() as session:
            
            total_urls = session.query(
                func.count(LinkModel.id)
            ).scalar()
            
            total_clicks = session.query(
                func.sum(LinkModel.clicks)
            ).scalar() or 0

            popular_links = (
                session.query(LinkModel)
                .order_by(LinkModel.clicks.desc())
                .limit(10)
                .all()
            )

            return {
                "total_urls": total_urls,
                "total_clicks": total_clicks,
                "popular_links": [self._to_domain(m) for m in popular_links],
            }

    def _to_domain(self, link_model: LinkModel) -> Link:
        """
        Convert a database model to a domain Link entity.

        If the model's datetime fields are naive (missing timezone information),
        they are assumed to be in UTC and are converted to timezone-aware UTC.
        This ensures that all domain entities consistently use aware datetimes.

        Args:
            link_model: SQLAlchemy LinkModel instance.

        Returns:
            Link: The corresponding domain entity.
        """

        created_at = link_model.created_at
        if created_at is not None and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        last_accessed = link_model.last_accessed
        if last_accessed is not None and last_accessed.tzinfo is None:
            last_accessed = last_accessed.replace(tzinfo=timezone.utc)

        return Link(
            id=link_model.id,
            url_hash=UrlHash(link_model.url_hash),
            short_code=ShortCode(link_model.short_code),
            original_url=OriginalUrl(link_model.original_url),
            created_at=created_at,
            clicks=link_model.clicks,
            last_accessed=last_accessed,
        )
