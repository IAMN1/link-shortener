from typing import List, Optional, Tuple
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, select, update
from link_shortener.database.database import transaction
from link_shortener.database.models import TableURL


class URLCrud:
    """Класс с CRUD операциями для таблицы ShortURL"""

    @staticmethod
    def create_or_get(
        source_url: str,
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
                    original_url=source_url,
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
    def bulk_create(urls_data: List[dict]) -> List[TableURL]:
        """Пакетное создание записей"""
        with transaction() as session:
            
            # 1. проверка хэшей на наличие в бд 
            hashes = [data['url_hash'] for data in urls_data]
            
            # Получение всех сущуствующих записий за один запрос
            existing_stmt = select(TableURL).where(TableURL.url_hash.in_(hashes))
            existing_records = {r.url_hash: r for r in session.execute(existing_stmt).scalars()}

            # Фильтруем
            new_data = [data for data in urls_data if data['url_hash'] not in existing_records]

            if new_data:
                # 2. Запись в БД
                elements = [
                    TableURL(
                        url_hash=data['url_hash'],
                        original_url=data['original_url'],
                        short_code=data['short_code'],
                    )
                    for data in new_data
                ]

            session.bulk_save_objects(elements)
            if new_data:
                session.expire_all()

            result_hashes = set(hashes)
            final_stmt = select(TableURL).where(TableURL.url_hash.in_(result_hashes))
            return session.execute(final_stmt).scalars().all()
    

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

            result = {
                'total_urls': total_urls,
                'total_clicks': total_clicks,
                'popular_urls': popular_urls
            }
            
            return result

# global instanse
table_url_crud = URLCrud()