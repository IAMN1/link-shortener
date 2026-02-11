from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import func
from domain.repositories.link_repository import LinkRepository
from sqlalchemy.orm import Session

from domain.entities.link import Link
from domain.value_objects.short_code import ShortCode
from domain.value_objects.url_hash import UrlHash
from domain.value_objects.original_url import OriginalUrl
from src.link_shortener.infrastructure.database.models import LinkModel

class SQLAlchemyLinkRepository(LinkRepository):
    """
    Реализация репозитория на SQLAlchemy
    Производит конвертацию доменных сущностей в модели ДБ
    """
    def __init__(self, session: Session):
        self.session = session
    
    def save(self, link: Link) -> Link:
        """Сохранение ссылки в БД"""
        link_model = LinkModel(
            id=link.id,
            url_hash=link.url_hash.value,
            short_code=link.short_code.value,
            original_url=link.original_url.value,
            created_at=link.created_at,
            clicks=link.clicks,
            last_accessed=link.last_accessed
        )

        self.session.add(link_model)
        self.session.flush()

        return self._to_domain(link_model)
    
    def save_many(self, links: List[Link]) -> List[Link]:
        """Пакетное сохранение в БД"""
        link_models = []
        for link in links:
            link_model = LinkModel(
                id=link.id,
                url_hash=link.url_hash.value,
                short_code=link.short_code.value,
                original_url=link.original_url.value,
                created_at=link.created_at,
                clicks=link.clicks,
                last_accessed=link.last_accessed
            )
            link_models.append(link_model)
        
        self.session.bulk_save_objects(link_models, return_defaults=False)
        self.session.flush()

        return links

    def find_by_code(self, short_code: ShortCode) -> Optional[Link]:
        """Поиск ссылки по коду"""
        link_model = self.session.query(LinkModel)\
            .filter_by(short_code=short_code.value)\
            .first()

        return self._to_domain(link_model) if link_model else None
    
    def find_by_codes(self, short_codes: List[ShortCode]) -> Dict[ShortCode, Optional[List[Link]]]:
        """Пакетный поиск по ссылок по кодам"""
        code_values = [sc.value for sc in short_codes]
        link_models = self.session.query(LinkModel)\
            .filter(LinkModel.short_code.in_(code_values))\
            .all()
        
        # Преобразовываение в словарь для быстрого поиска
        result = {
            ShortCode(model.short_code): self._to_domain(model)
            for model in link_models
        }

        # Добавление None для ненайденых кодов
        for code in short_codes:
            result.setdefault(code, None)
        
        return result

    def find_by_hash(self, url_hash: UrlHash) -> Optional[Link]:
        """Поиск ссылки по хэшу"""
        link_model = self.session.query(LinkModel)\
            .filter_by(url_hash=url_hash.value)\
            .first()
        
        return self._to_domain(link_model) if link_model else None
    
    def find_by_hashes(self, url_hashes: List[UrlHash]) -> Dict[UrlHash, Optional[Link]]:
        """Пакетный поиск ссылок по хэшам"""

        hash_values = [h.value for h in url_hashes]
        link_models = self.session.query(LinkModel)\
            .filter(LinkModel.url_hash.in_(hash_values))\
            .all()
        
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
        """Увеличение счетчика кликов"""
        self.session.query(LinkModel)\
            .filter_by(short_code=short_code.value)\
            .update({
                LinkModel.clicks: LinkModel.clicks + 1,
                LinkModel.last_accessed: datetime.now()
            },
            synchronize_session=False
        )
    
    def increment_clicks_batch(self, short_codes: List[ShortCode]) -> None:
        """Пакетное увеличение счетчика кликов"""
        code_values = [sc.value for sc in short_codes]

        # Bulk_update для эффективности
        self.session.query(LinkModel)\
            .filter(LinkModel.short_code.in_(code_values))\
            .update({
                LinkModel.clicks: LinkModel.clicks + 1,
                LinkModel.last_accessed: datetime.now()
            },
            synchronize_session=False
        )

    def get_stats(self) -> dict:
        """Получить статистику"""
        
        total_urls = self.session.query(func.count(LinkModel.id)).scalar()
        total_clicks = self.session.query(func.sum(LinkModel.clicks)).scalar() or 0
        
        popular_links = self.session.query(LinkModel)\
            .order_by(LinkModel.clicks.desc())\
            .limit(10)\
            .all()
        
        return {
            'total_urls': total_urls,
            'total_clicks': total_clicks,
            'popular_links': [self._to_domain(m) for m in popular_links]
        }
    
    def _to_domain(self, link_model: LinkModel) -> Link:
        """Конвертировать модель БД в доменную сущность"""
        return Link(
            id=link_model.id,
            url_hash=UrlHash(link_model.url_hash),
            short_code=ShortCode(link_model.short_code),
            original_url=OriginalUrl(link_model.original_url),
            created_at=link_model.created_at,
            clicks=link_model.clicks,
            last_accessed=link_model.last_accessed
        )