from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from link_shortener.core.exceptions import DatabaseError, DatabaseIntegrityError
from link_shortener.infrastructure.core.logging_config import get_logger
from link_shortener.domain.entities.link import Link
from link_shortener.domain.intefaces.abc_repository import ILinkRepository
from link_shortener.infrastructure.database.database_manager import Database
from link_shortener.infrastructure.database.models import TableURL


logger = get_logger(__name__)

class SQLAlchemyLinkRepository(ILinkRepository):
    """
    Реализация ILinkRepository на SQLAlchemy.
    Конвертирует доменные сущности в модели Базы данных и обратно
    """

    def __init__(self, database: Database):
        self.database = database
    
    def _from_domain(self, link: Link) -> TableURL:
        """Производит конвертацию доменной сущности в SQLAlchemy модель"""
        return TableURL(
            id=int(link.id) if link.id.isdigit() else None,
            url_hash=link.url_hash,
            short_code=link.short_code,
            original_url=link.original_url,
            created_at=link.created_at,
            clicks=link.clicks,
            last_accessed=link.last_accessed
        )
    
    def _to_domain(self, url_from_db: TableURL) -> Link:
        """Производит конвертацию SQLAlchemy модели в доменную сущность"""
        return Link(
            id = str(url_from_db.id),
            url_hash=url_from_db.url_hash,
            short_code=url_from_db.short_code,
            original_url=url_from_db.original_url,
            created_at=url_from_db.created_at,
            clicks=url_from_db.clicks,
            last_accessed=url_from_db.last_accessed
        )
    
    def create(self, link: Link) -> Link:
        """Создание новой ссылки"""
        try:
            with self.database.session() as session:
                db_url = self._from_domain(link)
                session.add(db_url)
                session.flush()

                # Обновление ID в доменной сущности
                link.id = str(db_url.id)
                logger.debug('Создана новая ссылка:', short_code=link.short_code)

                session.refresh(db_url)
                return self._to_domain(db_url)
        except IntegrityError as e:
            logger.error("Ошибка целостности при создании ссылки", error=str(e))
            raise DatabaseIntegrityError(message='Нарушение целостности данных при создании ссылки') from e
        except SQLAlchemyError as e:
            logger.error('ошибка базы данных при создании ссылки', error=str(e))
            raise DatabaseError('Ошибка базы данных при создании ссылки') from e
    
    def create_or_get(self, source_url: str, url_hash: str, short_code: str) -> Tuple[Link, bool]:
        """Создает или получает существующую ссылку"""
        try:
            with self.database.session() as session:
                # 1. попытка найти по хэшу существующую запись
                stmt = select(TableURL).where(TableURL.url_hash == url_hash)
                result = session.execute(stmt)
                existing = result.scalar_one_or_none()

                if existing:
                    logger.debug('Найдена существующая запись', url_hash=existing.url_hash)
                    return (self._to_domain(existing), False)
                
                # 2. Создание новой, если не нашли по хэшу
                db_url = TableURL(
                    url_hash=url_hash,
                    original_url=source_url,
                    short_code=short_code
                )
                session.add(db_url)
                session.flush()
                session.refresh(db_url)

                logger.info('Создана новая запись', short_code=short_code)
                return (self._to_domain(db_url), True)
            
        except IntegrityError as e:
            session.rollback()

            # Если произошла гонка, производим попытку снова найти ссылку
            result = session.execute(stmt)
            existing = result.scalar_one_or_none()
            
            if existing:
                logger.debug('Запись найдена после отката', record_id=existing.id)
                return (self._to_domain(existing), False)
            
            logger.error('Нарушение целостности при создании ссылки', error=str(e))
            raise DatabaseIntegrityError('Нарушение целостности данных при создании ссылки') from e
        except SQLAlchemyError as e:
            logger.error('Ошибка базы данных при создании ссылки', error=str(e))
            raise DatabaseError('ошибка базы данных при создании ссылки') from e

    def bulk_create(self, links_data: List[Dict]) -> List[Link]:
        """Производит пакетное создание ссылок"""
        if not links_data:
            return []
        try:
            with self.database.session() as session:
                
                # 1. проверка хэшей на наличие в бд
                hashes = [data['url_hash'] for data in links_data]

                # Извлечение всех существующих хэшей в бд присутствующих в списке
                stmt = select(TableURL).where(TableURL.url_hash.in_(hashes))
                existing_urls = session.execute(stmt).scalars().all()
                db_existing_hashes = {url.url_hash for url in existing_urls}

                logger.debug('Найдено существующих записей', total_hashes_count=len(hashes), existing_records_count=len(db_existing_hashes))
                
                # Список с новыми хэшами исключающий существующие в БД
                new_data = [
                    data for data in links_data
                    if data['url_hashes'] not in db_existing_hashes
                ]
                
                # Создание новых записей
                if new_data:
                    db_urls = [
                        TableURL(
                            url_hash=data['url_hash'],
                            original_url=data['original_url'],
                            short_code=data['short_code'],
                        )
                        for data in new_data
                    ]
                    session.bulk_save_objects(db_urls)
                    session.flush()

                # повторное извлечение всех записей по хэшу из бд 
                # (существующие + новые) присутствующих в списке hashes
                final_stmt = select(TableURL).where(TableURL.url_hash.in_(hashes))
                all_urls = session.execute(final_stmt).scalars().all()
                
                # конвертация в доменные сущности
                result = [self._to_domain(url) for url in all_urls]
                logger.info('Пакетное создание ссылок завершено', total_links_created=len(result), new_links=len(new_data))
                
                return  result
        except IntegrityError as e:
            logger.error('Ошибка целостности при пакетном создании', error=str(e))
            raise DatabaseIntegrityError('Нарушение целостности данных при пакетном создании ссылок') from e
        except SQLAlchemyError as e:
            logger.error('Ошибка базы данных при пакетном создании', error=str(e))
            raise DatabaseError('Ошибка базы данных при пакетном создании ссылок') from e

    def get_by_short_code(self, short_code: str) -> Optional[Link]:
        """Извлечение ссылки по короткому коду"""
        try:
            with self.database.session() as session:
                stmt = select(TableURL).where(TableURL.short_code == short_code)
                result = session.execute(stmt)
                url_from_db = result.scalar_one_or_none()

                if url_from_db:
                    logger.debug('Запись найдена', record_id=url_from_db.id)
                    return self._to_domain(url_from_db)
                else:
                    logger.debug('Запись по коду не найдена', short_code=short_code)
                
                return None
        except SQLAlchemyError as e:
            logger.error('Ошибка базы данных при поиске по коду', error=str(e))
            raise DatabaseError('Ошибка базы данных при поиске ссылки') from e

    def get_by_hash(self, url_hash: str) -> Optional[Link]:
        """Извлечение ссылки по хэшу URL"""
        try:
            with self.database.session() as session:
                stmt = select(TableURL).where(TableURL.url_hash == url_hash)
                result = session.execute(stmt)
                url_from_db = result.scalar_one_or_none()

                if url_from_db:
                    logger.debug('Запись найдена по хэшу', url_hash=url_from_db.url_hash[:10], short_code=url_from_db.short_code)
                    return self._to_domain(url_from_db)
                
                logger.debug('Запись по хэшу не найдена', url_hash=url_hash[:10])
                return None
        except SQLAlchemyError as e:
            logger.error('Ошибка базы данных при поиске по хэшу', error=str(e))
            raise DatabaseError('Ошибка базы данных при поиске ссылки по хэшу') from e

    def get_by_hashes(self, url_hashes: List[str]) -> List[Link]:
        """Пакетное извлечение ссылок по хэшам"""
        if not url_hashes:
            return []
        try:
            with self.database.session() as session:
                stmt = select(TableURL).where(TableURL.url_hash.in_(url_hashes))
                result = session.execute(stmt)
                urls_from_db = result.scalars().all()

                logger.debug('Пакетный поиск по хэшам', requested=len(url_hashes), founded=len(urls_from_db))
                return [self._to_domain(url) for url in urls_from_db]
            
        except SQLAlchemyError as e:
            logger.error('Ошибка базы данных при пакетном поиске', error=str(e))
            raise DatabaseError('Ошибка базы данных при пакетном поиске ссылок') from e

    def increment_clicks(self, short_code: str) -> bool:
        """Инкрементирует счетчик переходов"""
        try:
            with self.database.session() as session:
                update_stmt = (
                    update(TableURL)
                    .where(TableURL.short_code == short_code)
                    .values(
                        clicks=TableURL.clicks + 1,
                        last_accessed=func.now()
                    )
                )
                result = session.execute(update_stmt)

                updated = result.rowcount > 0

                if updated:
                    logger.debug('Счетчик успешно инкрементирован', short_code=short_code)
                    return True
                else:
                    logger.warning('Ссылка для инкремента не найдена в базе данных', short_code=short_code)
                    return False
        except SQLAlchemyError as e:
            logger.error('Ошибка базы данных при инкременте счетчика', error=str(e))
            raise DatabaseError('Ошибка базы данных при обновлении счетчика кликов ссылки') from e
    
    def get_stats(self) -> Dict:
        """Извлечение статистики сервиса"""
        try:
            with self.database.session() as session:
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
                    'popular_urls': [self._to_domain(url) for url in popular_urls]
                }
                
                logger.debug('Извлечена общая статистика сервиса', total_urls={total_urls}, total_clicks={total_clicks}, popular_urls={len(popular_urls)})
                
                return result
        except SQLAlchemyError as e:
            logger.error('Ошибка базы данных при получении статистики', error=str(e))
            raise DatabaseError('ошибка базы данных при получении статистики сервиса') from e
