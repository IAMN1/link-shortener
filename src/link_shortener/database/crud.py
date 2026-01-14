from sqlite3 import IntegrityError
from typing import List, Optional, Tuple

from sqlalchemy import func, select, update
from link_shortener.database.database import transaction
from link_shortener.database.models import TableURL


class URLCrud:
    """Класс с CRUD операциями для таблицы ShortURL"""

    @staticmethod
    def create_or_get(
        normalized_url: str,
        url_hash: str,
        short_code: str
    ) -> Tuple[TableURL, bool]:
        """
        Создание или получение существующей записи
        """
        with transaction() as session:
            # 1. пробуем найти по хэшу
            stmt = select(TableURL).where(TableURL.url_hash == url_hash)
            result = session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                return existing, False
            
            try:
                new_element = TableURL(
                    original_url=normalized_url,
                    url_hash=url_hash,
                    short_code=short_code
                )
                session.add(new_element)
                session.flush()
                return new_element, True
            except IntegrityError:
                session.rollback()

                result = session.execute(stmt)
                existing = result.scalar_one_or_none()

                if existing:
                    return existing, False
                else: 
                    raise
    
    
    @staticmethod
    def get_by_hash(url_hash: str) -> Optional[TableURL]:
        """ быстрый поиск по хэшу"""
        with transaction() as session:
            stmt = select(TableURL).where(TableURL.url_hash == url_hash)
            result = session.execute(stmt)
            return result.scalar_one_or_none()
    

    @staticmethod
    def get_by_short_code(short_code: str, increment_click: bool = True) -> Optional[TableURL]:
        """Получение по коду с опциональным увелечением счетчика"""
        with transaction() as session:
            stmt = select(TableURL).where(TableURL.short_code == short_code)
            result = session.execute(stmt)
            element = result.scalar_one_or_none()

            if element and increment_click:
                update_stmt = (
                    update(TableURL)
                    .where(TableURL.id == element.id)
                    .values(
                        clicks=TableURL.clicks + 1,
                        last_accessed=func.now()
                    )
                )
                session.execute(update_stmt)
            
            return element
    

    @staticmethod
    def bulk_create(urls_data: list[dict]) -> List[TableURL]:
        """Пакетное создание записей"""
        with transaction() as session:
            elements = [
                TableURL(
                    original_url=data['original_url'],
                    url_hash=data['url_hash'],
                    short_url=data['short_url'],
                )
                for data in urls_data
            ]

            session.bulk_save_objects(elements)
            return elements
    

    @staticmethod
    def get_stats() -> dict:
        """Получение статистики сервиса"""
        with transaction() as session:
            # Общее количество ссылок
            total_stmt = select(func.count(TableURL.id))
            total_urls = session.execute(total_stmt).scalar()

            # Сумма кликов
            clicks_stmt = select(func.sum(TableURL.clicks))
            total_clicks = session.execute(clicks_stmt).scalar() or 0

            # Самые популярные
            popular_stmt = select(TableURL).order_by(TableURL.clicks.desc()).limit(10)
            popular_urls = session.execute(popular_stmt).scalars().all()

            return {
                'total_urls': total_urls,
                'total_clicks': total_urls,
                'avg_clicks_per_url': total_clicks / total_urls if total_clicks else 0,
                'popular_urls': [{
                    'short_code': url.short_code,
                    'clicks': url.clicks,
                    'original_url': (url.original_url[:50] + '...' 
                                     if len(url.original_url) > 50 
                                     else url.original_url)
                } for url in popular_urls]
            }

# global instanse
table_url_crud = URLCrud()