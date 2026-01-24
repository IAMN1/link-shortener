from typing import Dict, List
from link_shortener.core.config import BaseConfig
from link_shortener.core.logging_config import get_logger
from link_shortener.database.crud import URLCrud
from link_shortener.database.models import TableURL
from link_shortener.core.exceptions import NotFoundError, ServiceError, ValidationError
from link_shortener.utils.short_code_generator import HashBasedGenerator
from link_shortener.utils.url_validators import UrlValidator


logger = get_logger(__name__)

class LinkService:
    def __init__(self, code_generator=None, base_url=None, cache_client=None):
        self.generator = code_generator or HashBasedGenerator(
            code_length=BaseConfig.SHORT_CODE_LENGTH, 
            pepper=BaseConfig.SHORT_CODE_SECRET_PEPPER
        )
        self.base_url = base_url or BaseConfig.BASE_LINK
        self.cache = cache_client


        logger.info(
            'LinkService_initialized',
            short_code_length=BaseConfig.SHORT_CODE_LENGTH,
            base_url=self.base_url,
        )

    
    def create_short_url(self, original_url: str) -> Dict:
        """
        Создание короткой URL

        Args:
            original_url (str): Оригинальная URL

        Returns:
            dict: Словарь с результатом
        """
        
        logger.info(
            'Начало создания короткиой ссылки',
            original_url=original_url[:50] + "..." if len(original_url) > 50 else original_url
        )

        # Валидация и нормализация url
        is_valid, url_or_message = UrlValidator.is_valid_url(original_url)
        if not is_valid:
            logger.warning(
                'Невалидный URL',
                original_url=original_url,
                validation_error=url_or_message
            )
            raise ValidationError(url_or_message, 'INVALID_URL')
        
        normalized_url = url_or_message
        logger.debug('URL нормализован', normalized_url=normalized_url)

        # TODO добавить проверку кэша
        # Проверка кэша (уменьшает нагрузку на БД)

        # Генерация хэша для дедупликации и кода
        url_hash = self.generator.calculate_deduplication_hash(normalized_url)
        short_code = self.generator.generate_code(normalized_url)
        logger.debug(
            'hash_and_code_generated',
            url_hash=url_hash[:10],
            short_code=short_code
        )

        # Сохранение в бд
        try:
            logger.debug('Запись нового элемента в базу данных...')
            short_url, is_created = URLCrud.create_or_get(
                source_url=original_url,
                url_hash=url_hash,
                short_code=short_code
            )
            
            # Формирование ответа
            response = self._format_response(short_url, is_created)

            if is_created:
                logger.info(
                    'Новая короткая ссылка успешно создана',
                    short_code=short_code,
                    original_url=normalized_url[:50]
                )
            else:
                logger.info(
                    'Найдена существующая ссылка',
                    short_code=short_code,
                    clicks_count=short_url.clicks
                )

            # TODO Добавить кэширование созданного элемента
            
            # TODO Добавить логирование

            return response
        
        except ValidationError:
            logger.error('Ошибка валидации URL', original_url=original_url)
            raise # top level
        except Exception as e:
            logger.error(
                'Ошибка при создании короткой ссылки для URL',
                original_url=original_url,
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True
            )
            raise ServiceError(
                "Внутренняя ошибка при создании ссылки",
                "SERVICE_ERROR"   
            )
    
    def get_original_url(self, short_code: str) -> Dict:
        """
        Получение оригинального URL

        Args:
            short_code (str): Короткий код

        Returns:
            Dict: словарь с данными URL
        """
        #   TODO добавить логику получения из короткой ссылки кода
        #   и полчение оригинальной ссылки 
        #   (переделать логику или добавить отсутствующую реализацию) 

        try:
            logger.info('Получение оригинального URL по коду', short_code=short_code)

            # Проверка кэша
            # TODO Добавить проверку наличия в кэше

            # Поиск и извлечение из БД
            logger.debug('Поиск кода в Базе данных...', short_code=short_code)
            element = URLCrud.get_by_short_code(short_code)

            if not element:
                logger.warning('запись в базе данных не найдена')
                raise NotFoundError(
                    f'Короткая ссылка c {short_code} не найдена', 
                    'URL_NOT_FOUND'
                )
            

            logger.info(
                'Запись найдена',
                short_code=short_code,
                original_url=element.original_url[:50],
                clicks_count=element.clicks,
            )

            return {
                'url_hash': element.url_hash,
                'original_url': element.original_url,
                'short_url': f'{self.base_url}{short_code}',
                'short_code': short_code,
                'clicks': element.clicks,
                'created_at': element.created_at.isoformat(),
                'last_accessed': element.last_accessed.isoformat() if element.last_accessed else None,
            }
        except (NotFoundError):
            raise # top level
        except Exception as e:
            logger.error(
                'Ошибка при получении ссылки по коду',
                short_code=short_code,
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True
            )
            raise ServiceError(
                'Внутрення ошибка при получении ссылки',
                'SERVICE_ERROR'
            )
    
    def batch_create(self, urls: List[str]) -> List[Dict]:
        """
        Пакетное создание ссылок

        Args:
            urls (List[str]): Список URL

        Returns:
            List[Dict]: Список созданных URL
        """
        logger.info(
            'Начато пакетное создание ссылок', 
            urls_count=len(urls),
            batch_limit=BaseConfig.BATH_CREATE_LIMIT
        )

        if len(urls) > BaseConfig.BATH_CREATE_LIMIT:
            logger.warning(
                'Превышен лимит допустимого пакетного создания: '
                f'{len(urls)} > {BaseConfig.BATH_CREATE_LIMIT}'
            )

        # Массив с созданными ссылками и ошибочными при нормализации
        results = []
        # Массим с успешно нормализованными ссылками
        url_data_for_bulk = []
        invalid_count = 0
        error_count = 0
        # 1. Обработка ссылок
        logger.debug('Этап 1 - Валидация URLs')

        for url in urls:
            try:
                # Валидация
                is_valid, url_or_message = UrlValidator.is_valid_url(url)
                if not is_valid:

                    invalid_count += 1
                    
                    logger.debug(
                        'Невалидный URL в пакете', 
                        original_url=url, 
                        error=url_or_message
                    )
                    
                    results.append({
                        'success': False,
                        'url': url,
                        'error': url_or_message,
                        'code': 'INVALID_URL'})
                    continue

                # Генерация хэшей и кодов для ссылок
                url_hash = self.generator.calculate_deduplication_hash(url_or_message)
                short_code = self.generator.generate_code(url_or_message)

                url_data_for_bulk.append({
                    'url_hash': url_hash,
                    'original_url': url_or_message,
                    'short_code': short_code
                })
            
            except Exception as e:
                error_count += 1

                logger.error(
                    'Ошибка при обработке URL',
                    original_url=url, 
                    error=str(e),
                    error_type=type(e).__name__,
                    exc_info=True
                )
                results.append({
                    'success': False,
                    'url': url,
                    'error': url_or_message,
                    'code': 'PROCESSING_ERROR'
                })
        
        logger.debug(
            'Этап 1 - завершен',
            total_validated=len(url_data_for_bulk),
            invalid_count=invalid_count,
            error_count=error_count
        )

        # 2. Пакетное сохранение в БД
        if url_data_for_bulk:
            try:
                logger.debug(
                    'Этап 2 - Пакетное сохранение в базу данных',
                    record_count=len(url_data_for_bulk)
                )
                
                created_urls = URLCrud.bulk_create(url_data_for_bulk)

                logger.debug(
                    'Этап - 2 завершен',
                    saved_records_count=len(created_urls)
                )

                for url in created_urls:
                    results.append(self._format_response(url, True))

            except Exception as e:
                logger.error(
                    'Ошибка при пакетном сохранении в базу данных',
                    error=str(e),
                    error_type=type(e).__name__,
                    exc_info=True
                )

                for data in url_data_for_bulk:
                    results.append({
                        'success': False,
                        'url': data['original_url'],
                        'error': 'Ошибка при сохранении в БД',
                        'code': 'DB_SAVE_ERROR'
                    })
        total_processed = len(results)
        success_count = sum(1 for item in results if item.get('success', False))
        
        logger.info(
            'Пакетное создание завершено',
            total_processed=total_processed,
            success_count=success_count,
            failed_count=total_processed - success_count
        )
        return results
    
    def get_service_stats(self) -> Dict:
        """
        Получение статистики сервиса

        Returns:
            Dict: Стастистика
        """
        logger.info('Запрос общей статистики сервиса')

        try:

            stats = URLCrud.get_stats()
            
            total_urls = stats.get('total_urls', 0)
            total_clicks = stats.get('total_clicks', 0)
            avg_clicks = round((total_clicks /  total_urls if total_clicks else 0), 2)
            popular_urls = stats.get('popular_urls', [])

            logger.info(
                'Извлечена общая статистика сервиса',
                total_urls=total_urls,
                total_clicks=total_clicks,
                avg_clicks=avg_clicks
            )

            return {
                'total_urls': total_urls,
                'total_clicks': total_clicks,
                'avg_clicks_per_url': avg_clicks,
                'popular_urls': [{
                    'short_code': url.short_code,
                    'short_url': f'{self.base_url}{url.short_code}',
                    'clicks': url.clicks,
                    'original_url': (url.original_url[:50] + '...' 
                                    if len(url.original_url) > 50 
                                    else url.original_url)
                } for url in popular_urls]
            }
        except Exception as e:
            logger.error(
                'Ошибка при получении общей статистики', 
                error={str(e)},
                error_type=type(e).__name__,
                exc_info=True)

            raise ServiceError(
                'Ошибка при получении общей статистики',
                'STATS_ERROR'
            )
    
    def cleanup_cache(self):
        """
        Очистка кэша
        """
        
        logger.info('Инициализирована очистка кэша')

        # TODO Добавить отчистку кэша
        pass
    
    def _format_response(self, element: TableURL, created: bool) -> Dict:
        """Форматирование итогового ответа"""

        result = {
            'already_exists': not created,
            'short_code': element.short_code,
            'short_url': f'{self.base_url}{element.short_code}',
            'original_url': element.original_url,
            'clicks': element.clicks,
            'created_at': element.created_at.isoformat(),
            'message': 'Ссылка уже существует' if not created else 'Ссылка успешно создана'
        }

        if element.last_accessed:
            result['last_accessed'] = element.last_accessed.isoformat()
        
        return result

# instance
link_service = LinkService()
