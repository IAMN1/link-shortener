from typing import List, Optional, Tuple
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, select, update
from link_shortener.core.logging_config import get_logger
from link_shortener.database.database import transaction
from link_shortener.database.models import TableURL


logger = get_logger(__name__)

class URLCrud:
    """Класс с CRUD операциями для таблицы ShortURL"""

    @staticmethod
    def create_or_get(source_url: str, url_hash: str, short_code: str) -> Tuple[TableURL, bool]:
        """
        Создание или получение существующей записи
        """

        logger.debug(
            'create_or_get',
            url_hash=url_hash[:10],
            short_code=short_code
        )

        with transaction() as session:
            # 1. Проверяем по хэшу есть ли такая запись
            stmt = select(TableURL).where(TableURL.url_hash == url_hash)
            result = session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                logger.debug('Найдена существующая запись', record_id=existing.id)
                return existing, False
            
            try:
                # 2. Создаем запись
                new_element = TableURL(
                    original_url=source_url,
                    url_hash=url_hash,
                    short_code=short_code
                )
                session.add(new_element)
                session.flush()

                logger.info(
                    'Создана новая запись',
                    record_id=new_element.id,
                    short_code=short_code
                )
                
                return new_element, True
            
            except IntegrityError as e:
                logger.error(
                    'IntegrityError', 
                    error=str(e),
                    error_type=type(e).__name__, 
                    exc_info=True
                )

                session.rollback()

                result = session.execute(stmt)
                existing = result.scalar_one_or_none()

                if existing:
                    logger.debug('Запись найдена после отката', record_id=existing.id)
                    return existing, False
                else: 
                    raise
    
    @staticmethod
    def get_by_hash(url_hash: str) -> Optional[TableURL]:
        """ быстрый поиск по хэшу"""

        logger.debug('get_by_hash', url_hash=url_hash[:10])

        with transaction() as session:
            stmt = select(TableURL).where(TableURL.url_hash == url_hash)
            result = session.execute(stmt)
            element = result.scalar_one_or_none()

            if element:
                logger.debug(
                    'Запись найдена по хэшу',
                    record_id=element.id,
                    short_code=element.short_code,
                )
            else:
                logger.debug('Запись по хэшу не найдена')

            return element
    
    @staticmethod
    def get_by_hashes(url_hashes: List) -> List[TableURL]:
        """Пакетное получение хэшей"""
        logger.debug('get_by_url_hashes', hashes_count=len(url_hashes))

        if not url_hashes:
            return []
        
        with transaction() as session:
            stmt = select(TableURL).where(TableURL.url_hash.in_(url_hashes))
            result = session.execute(stmt)
            elements = result.scalars().all()

            logger.debug(
                'Найдено записей по хэшам',
                requested=len(url_hashes),
                founded=len(elements)
            )
            return elements

    @staticmethod
    def get_by_short_code(short_code: str, increment_click: bool = True) -> Optional[TableURL]:
        """Получение по коду с опциональным увелечением счетчика"""

        logger.debug(
            'get_by_short_code',
            short_code=short_code,
            increment_click=increment_click
        )

        with transaction() as session:
            stmt = select(TableURL).where(TableURL.short_code == short_code)
            result = session.execute(stmt)
            element = result.scalar_one_or_none()

            if element:
                logger.info(
                    'Запись найдена',
                    record_id=element.id,
                    clicks_count=element.clicks
                )
                
                if increment_click:
                    update_stmt = (
                        update(TableURL)
                        .where(TableURL.id == element.id)
                        .values(
                            clicks=TableURL.clicks + 1,
                            last_accessed=func.now()
                        )
                    )
                    session.execute(update_stmt)

                    logger.info(
                        'Счетчик кликов для записи', 
                        record_id=element.id,
                        clicks_count=element.clicks + 1
                    )
            else:
                logger.debug('Запись по коду не найдена', short_code=short_code)

            return element
    
    @staticmethod
    def bulk_create(urls_data: List[dict]) -> List[TableURL]:
        """Пакетное создание записей"""

        logger.info('bulk_create', record_count=len(urls_data))

        with transaction() as session:
            
            # 1. проверка хэшей на наличие в бд 
            hashes = [data['url_hash'] for data in urls_data]

            logger.debug('Проверка хэшей', hash_count=len(hashes))
            
            # Получение всех существующих записий за один запрос
            existing_stmt = select(TableURL).where(TableURL.url_hash.in_(hashes))
            existing_records = {r.url_hash: r for r in session.execute(existing_stmt).scalars()}

            logger.debug(
                'Найдено существующих записей', 
                existing_records_count=len(existing_records))

            # Фильтруем
            new_data = [data for data in urls_data if data['url_hash'] not in existing_records]
            
            logger.debug('Новых записей для создания', new_records_count=len(new_data))
            
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
            
            logger.info('Создано новых записей', created_records_count=len(elements))
            
            if new_data:
                session.expire_all()

            result_hashes = set(hashes)
            final_stmt = select(TableURL).where(TableURL.url_hash.in_(result_hashes))
            result = session.execute(final_stmt).scalars().all()

            logger.debug(
                'Всего создано записей после операции',
                total_records_created=len(result)
                )

            return result
    
    @staticmethod
    def get_stats() -> dict:
        """Получение статистики сервиса"""

        logger.debug('Получение статистики сервиса')

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
            
            logger.info(
                'Извлечена общая статистика сервиса',
                total_urls={total_urls},
                total_clicks={total_clicks},
                popular_urls={len(popular_urls)}
            )

            return result

    @staticmethod
    def increment_clicks(short_code: str) -> bool:
        """увеличение счетчика кликов"""
        logger.debug('increment_clciks', short_code=short_code)

        with transaction() as session:
            update_stmt = (
                update(TableURL).where(TableURL.short_code == short_code)
                .values(clicks=TableURL.clicks + 1, last_accessed=func.now())
            )
            result = session.execute(update_stmt)
            session.commit()

            updated = result.rowcount > 0
            logger.debug(
                'Инкремент счетчика клика',
                short_code=short_code,
                updated=updated
            )
            return updated