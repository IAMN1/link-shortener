from typing import Dict, List

from link_shortener.domain.intefaces.abc_code_generator import ICodeGenerator
from link_shortener.domain.intefaces.abc_url_validator import IUrlValidator
from link_shortener.infrastructure.core.logging_config import get_logger
from link_shortener.core.exceptions import NotFoundError, ServiceError, ValidationError
from link_shortener.domain.entities.link import Link
from link_shortener.domain.intefaces.abc_cache import ICacheClient
from link_shortener.domain.intefaces.abc_repository import ILinkRepository



logger = get_logger(__name__)

class LinkService:
    def __init__(self, repository: ILinkRepository, base_url: str, url_validator: IUrlValidator, code_generator: ICodeGenerator, cache_client: ICacheClient, cache_ttl: int = 3600, cache_ttl_stats: int = 300, batch_limit: int = 100):
        self.repository = repository
        self.base_url = base_url
        self.cache = cache_client
        self.cache_ttl = cache_ttl
        self.generator = code_generator
        self.url_validator=url_validator
        self.cache_ttl_stats = cache_ttl_stats
        self.batch_limit = batch_limit

        self.CACHE_PREFIX_REDIRECT = "redirect:"
        self.CACHE_PREFIX_HASH = "hash:"
        self.CACHE_KEY_STATS = "service_stats"

        logger.info('LinkService_initialized', base_url=self.base_url, cache_enabled=self.cache is not None)
   
    def create_short_url(self, original_url: str) -> Dict:
        """
        Создание короткой URL

        Args:
            original_url (str): Оригинальная URL

        Returns:
            dict: Словарь с результатом
        """
        try:
            logger.info('Начало создания короткиой ссылки', url_length=len(original_url))

            # 1. Валидация и нормализация url
            is_valid, url_or_message = self.url_validator.is_valid_url(original_url)
            if not is_valid:
                logger.warning('Невалидный URL', original_url=original_url, validation_error=url_or_message)
                raise ValidationError(url_or_message, 'INVALID_URL')

            # 2. Генерация хэша для дедупликации и кода
            url_hash = self.generator.calculate_deduplication_hash(url_or_message)
            logger.debug('url_hash_generated', hash=url_hash[:10])
            
            # 3. Проверка кэша по хэшу Url на дедупликацию
            cache_key_hash = f'{self.CACHE_PREFIX_HASH}{url_hash}'
            if self.cache:
                cached_code = self.cache.get(cache_key_hash)
                if cached_code:
                    logger.info('Найден код ссылки в кэше дедупликации', hash=url_hash[:10])
                    existing_link = self.repository.get_by_short_code(cached_code)
                    if existing_link:
                        logger.info('Возврат ссылки из кэша', short_code=cached_code)
                        return self._format_url_response(existing_link, is_new=False)

            # 4. Генерация короткого кода для ссылки
            short_code = self.generator.generate_code(url_or_message)
            logger.debug('short_code_generated', short_code=short_code)

            # 5. Сохранение в бд или получение, если уже существует запись с таким хэшем
            short_link, is_created = self.repository.create_or_get(
                url_hash=url_hash,
                source_url=original_url,
                short_code=short_code
            )

            if is_created:
                logger.info('Короткая ссылка успешно создана', url_hash=url_hash[:10], short_code=short_code)
                
                # 6. Кэширование короткого кода для дедупликации (hash: short_code)
                if self.cache:
                    is_cached_by_url_hash = self.cache.set(cache_key_hash, short_code, ttl=self.cache_ttl)
                    
                    if is_cached_by_url_hash:
                        logger.info('Данные ссылки успешно закэшированы', redis_key=cache_key_hash)
                    else:
                        logger.warning('Возникли проблемы с кэшированием данных', short_code=short_code, url=url_or_message)
            else:
                logger.info('Найдена существующая ссылка', short_code=short_code, clicks_count=short_link.clicks)

            return self._format_url_response(short_link, is_new=is_created)
        
        except ValidationError:
            logger.error('Ошибка валидации URL', original_url=original_url)
            raise # top level
        except Exception as e:
            logger.error(
                'Ошибка при создании короткой ссылки для URL',
                error_type=type(e).__name__,
                original_url=original_url,
                error=str(e),
                exc_info=True
            )
            raise ServiceError("Внутренняя ошибка при создании короткой ссылки", "SERVICE_ERROR")
    
    def get_original_url_for_refirect(self, short_code: str) -> str:
        """Получение оригинального url для редиректа"""
        try:
            logger.info('Начало редиректа по короткому коду', short_code=short_code)

            # 1. Проверка кэша редиректа
            cache_key_redirect = f'{self.CACHE_PREFIX_REDIRECT}{short_code}'
            if self.cache:
                cached_link = self.cache.get(cache_key_redirect)
                if cached_link:
                    logger.info('Ссылка найдена в кэше', short_code=short_code, cached_link=cached_link)

                    # Обновление счетчика переходов по ссылке в базе данных
                    is_updated = self.repository.increment_clicks(short_code)
                    if is_updated:
                        logger.info('Счетчик перехода по ссылке обновлен')
                    else:
                        logger.warning('Не дуалось обновить счетчик перехода по ссылке', short_code=short_code)
                    return cached_link
            
            # 2. Извлечение из БД если нет данных в кэше
            link = self.repository.get_by_short_code(short_code)
            
            if not link:
                logger.warning('Запись в базе данных не найдена', short_code=short_code)
                raise NotFoundError(f'Ссылка c кодом {short_code} не найдена')
            
            # 3. Инкрементирование счетчика кликов в доменной сущности и записи в БД
            link.increment_clicks()
            self.repository.increment_clicks(short_code)

            # 4. Кэширование для будущих редиректов
            if self.cache:
                is_cached = self.cache.set(cache_key_redirect, link.original_url, self.cache_ttl)
                if is_cached:
                    logger.info('Ссылка успешно закэширована', redis_key=cache_key_redirect)
                else:
                    logger.warning('Возникли проблемы с кэшированием ссылки', short_code=short_code)
            

            logger.info('Ссылка для редиректа получена', short_code=short_code, original_url=link.original_url[:50])
            return link.original_url
            
        except (NotFoundError):
            raise # top level
        except Exception as e:
            logger.error(
                'Ошибка при получении ссылки по коду для редиректа',
                short_code=short_code,
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True
            )
            raise ServiceError('Внутрення ошибка при получении ссылки для редиректа')

    def get_url_info(self, short_code: str) -> Dict:
        """
        Получение информации по короткому коду о ссылке
        Данные берутся всегда из БД

        Args:
            short_code (str): Короткий код

        Returns:
            Dict: словарь с данными URL
        """ 

        try:
            logger.info('Получение информации о ссылке по коду', short_code=short_code)

            # 1. получение данных из БД
            link = self.repository.get_by_short_code(short_code)

            if not link:
                logger.warning('Запись в базе данных не найдена')
                raise NotFoundError(f'Короткая ссылка c {short_code} не найдена', 'URL_NOT_FOUND')

            logger.info('Информация о ссылке найдена в базе данных', url_hash=link.url_hash[:10], short_code=short_code, from_cache=False)

            return {
                'url_hash': link.url_hash,
                'short_code': short_code,
                'short_url': f'{self.base_url}{short_code}',
                'original_url': link.original_url,
                'clicks': link.clicks,
                'created_at': link.created_at.isoformat(),
                'last_accessed': link.last_accessed.isoformat() if link.last_accessed else None,
            }
        except NotFoundError:
            raise # top level
        except Exception as e:
            logger.error(
                'Ошибка при получении информации о ссылке по коду',
                short_code=short_code,
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True
            )
            raise ServiceError('Внутрення ошибка при получении информации о ссылке', 'SERVICE_ERROR')
    
    def batch_create(self, urls: List[str]) -> List[Dict]:
        """
        Пакетное создание ссылок

        Args:
            urls (List[str]): Список URL

        Returns:
            List[Dict]: Список созданных URL согласно схеме BatchURLSResponse
        """
        try:
            logger.info('Начато пакетное создание ссылок', urls_count=len(urls), batch_limit=self.batch_limit)

            if len(urls) > self.batch_limit:
                logger.warning(
                    'Превышен лимит допустимого пакетного создания, ' \
                    'длинну урезаем до лимита: '
                    f'{len(urls)} > {self.batch_limit}'
                )
                # Урезаем список ссылок до лимита
                urls = urls[:self.batch_limit]
            
            # 1. Валидация ссылок
            # Массив с созданными ссылками и ошибочными при валидации
            valid_data = []
            results = []
            invalid_count = 0

            for url in urls:
                
                # 1.1 Валидация
                is_valid, url_or_message = self.url_validator.is_valid_url(url)
                
                if not is_valid:    
                    logger.warning('Невалидный URL в пакете', original_url=url, error=url_or_message)

                    invalid_count += 1
                    results.append({
                        'success': False,
                        'source_url': url,
                        'error': url_or_message
                    })
                    continue

                # 1.2 Генерация хэшей и кодов для ссылок
                url_hash = self.generator.calculate_deduplication_hash(url_or_message)
                short_code = self.generator.generate_code(url_or_message)
                
                valid_data.append({
                    'url_hash': url_hash,
                    'original_url': url,
                    'short_code': short_code
                })

            logger.debug('Валидация ссылок завершена', total_validated=len(valid_data), invalid_count=invalid_count)

            if not valid_data:
                return {
                    'results':results,
                    'total': len(results),
                    'successful': 0,
                    'failed': len(results)
                }

            # 2. Пакетная проверка дедупликации в кэше и Базе данных
            # Группирование данных по хэшам для быстрого поиска
            hash_to_data = {data[url_hash]: data for data in valid_data}
            hashes_to_check = list(hash_to_data.keys())

            ## 2.1 Проверка в кэше
            if self.cache and valid_data:
                cache_keys = [f'{self.CACHE_PREFIX_HASH}{hash}' for hash in hashes_to_check]
                
                cached_results = self.cache.get_many(cache_keys)

                # Создаем набор существующих хэшей
                existing_hashes = {
                    url_hash
                    for url_hash, cache_key in zip(hashes_to_check, cache_keys)
                    if cached_results.get(cache_key)
                }
            
            ## 2.2 Проверка в бд для оставшихся хэшей не найденных в кэше
            # Отнимаем существующие хэши найденные в кэше
            hashes_to_check = [hash for hash in hashes_to_check if hash not in existing_hashes]
            
            if hashes_to_check:

                existing_links_in_db = self.repository.get_by_hashes(hashes_to_check)
                
                for links in existing_links_in_db:

                    existing_hashes.add(links.url_hash)
                    
                    results.append({
                        'success': True,
                        'already_exists': True,
                        'source_url': links.original_url,
                        'short_url': f'{self.base_url}{links.short_code}',
                        'short_code': links.short_code,
                    })

            logger.debug('Проверка дедупликации завершена', total_for_check=len(hash_to_data), founded_in_cache_or_db=existing_hashes)

            # Подготовка списка новых URL для пакетного сохранения в БД
            new_links = [
                {
                    'url_hash': link['url_hash'],
                    'original_url': link['original_url'],
                    'short_code': link['short_code']
                }
                for link in valid_data
                if link['url_hash'] not in existing_hashes
            ]

            # 3. Пакетное сохранение в БД
            if new_links:
                created_links = self.repository.bulk_create(new_links)

                logger.debug('Пакетное сохранение ссылок в базу данных завершено', saved_links_count=len(created_links))
            
            # 4. Пакетное кеширование
            if self.cache and created_links:
                # Кэширование для дедупликации (prefix+hash: short_code)
                cache_data_deduplication = {}
                # Кэширование для редиректов (prefix+short_code: original_url)
                cache_data_redirect = {}

                for link in created_links:
                    cache_key_hash = f'{self.CACHE_PREFIX_HASH}{link.url_hash}'
                    cache_key_redirect = f'{self.CACHE_PREFIX_REDIRECT}{link.short_code}'

                    cache_data_deduplication[cache_key_hash] = link.short_code
                    cache_data_redirect[cache_key_redirect] = link.original_url
                
                if cache_data_deduplication and cache_data_redirect:
                    self.cache.set_many(cache_data_deduplication, ttl=self.cache_ttl)
                    self.cache.set_many(cache_key_redirect, ttl=self.cache_ttl)
                
                logger.debug('Пакетное кэширование завершено', deduplication_records=len(cache_data_deduplication), redirect_records=len(cache_data_redirect))

            # 5. Формирование результатов для ссылок
            for link in created_links:
                results.append(
                    {
                        'success': True,
                        'already_exists': False,
                        'source_url': link.original_url,
                        'short_url': f'{self.base_url}{link.short_code}',
                        'short_code': link.short_code,
                    }
                )

            # 6 расчет статистики обработки ссылок
            total_processed = len(results)
            success_count = sum(1 for item in results if item.get('success', False))
            failed_count = total_processed - success_count
            
            logger.info(
                'Пакетное создание завершено',
                total_processed=total_processed,
                success_count=success_count,
                failed_count=failed_count
            )

            # 7. Формирование ответа
            response = {
                "results": results,
                "total": total_processed,
                "successful": success_count,
                "failed": failed_count
            }

            return response
        
        # TODO добавить обрабтку конкретных возможных ошибок
        # 
        # 
        # 
        except Exception as e:
            logger.error(
                'Непредвиденная ошибка при пакетной генерации коротких ссылок',
                urls_count=len(urls),
                urls_list=urls,
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True
            )
            raise ServiceError('Внутрення ошибка пакетной генерации коротких ссылок')
  
    def get_link_service_stats(self) -> Dict:
        """
        Получение статистики сервиса

        Returns:
            Dict: Стастистика сервиса. Согласно схеме ServiceStatsResponse
        """
        logger.info('Запрос общей статистики сервиса')

        try:
            # 1. Попытка получения данных из кэша
            if self.cache:
                cached_stats = self.cache.get(self.CACHE_KEY_STATS)
                if cached_stats:
                    logger.info('Статистика получена из кэша')
                    return cached_stats

            # 2. Получение статистики из БД
            stats = self.repository.get_stats()
            
            # Формирование ответа
            total_urls = stats.get('total_urls', 0)
            total_clicks = stats.get('total_clicks', 0)
            avg_clicks = round((total_clicks /  total_urls if total_clicks else 0), 2)
            popular_urls = stats.get('popular_urls', [])

            result = {
                'total_urls': total_urls,
                'total_clicks': total_clicks,
                'avg_clicks_per_url': avg_clicks,
                'popular_urls': [{
                    'short_code': url.short_code,
                    'short_url': f'{self.base_url}{url.short_code}',
                    'original_url': (url.original_url[:50] + '...' 
                                    if len(url.original_url) > 50 
                                    else url.original_url),
                    'clicks': url.clicks,
                    'created_at': url.created_at
                } for url in popular_urls]
            }

            # 3. Кэширование статистики
            if self.cache:
                is_cached_stats = self.cache.set(self.CACHE_KEY_STATS, result, self.cache_ttl_stats)
                if is_cached_stats:
                    logger.debug('Общая статистика успешно закэширована')
                else:
                    logger.warning('Не удалось кэшировать статистику')

            logger.info('Извлечена общая статистика сервиса', total_urls=total_urls, total_clicks=total_clicks, avg_clicks=avg_clicks)
            return result
        
        except Exception as e:
            logger.error(
                'Ошибка при получении общей статистики', 
                error={str(e)},
                error_type=type(e).__name__,
                exc_info=True)

            raise ServiceError('Ошибка при получении общей статистики','STATS_ERROR')
    
    def cleanup_cache(self) -> Dict:
        """
        Очистка кэша
        """
        
        logger.info('Инициализирована очистка кэша')

        if not self.cache:
            return {
                'succes': False,
                'message': 'Кэш клиент не инициализирован',
                'cache_stats': None
            }
        
        try:
            # Получение статистики перед очисткой
            stats_before = self.cache.get_stats()
            clear_result = self.cache.clear()
            stats_after = self.cache.get_stats()

            if clear_result:

                result = {
                    'success': clear_result,
                    'message': 'Кэш успешно очищен',
                    'cache_stats': {
                        'before_cleanup': stats_before, # пока что в схеме не используется
                        'after_cleanup': stats_after    # пока что в схеме не используется
                    }
                }

                logger.info('Кэш успешно очищен', stats_before=stats_before, stats_after=stats_after)
            else:
                logger.warning('Очистка кэша провалилась')
                result = {
                    'success': clear_result,
                    'message': 'Очистка кэша провалилась',
                    'cache_stats': {
                        'before_cleanup': stats_before,
                        'after_cleanup': stats_after
                    }
                }
            
            return result
        
        except Exception as e:
            logger.error(
                'Ошибка при отчистке кэша',
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True
            )
            return {
                'success': clear_result,
                'message': 'Ошибка при отчистке кэша',
                'cache_stats': {
                    'before_cleanup': stats_before,
                    'after_cleanup': stats_after
                }
            }

    def _format_url_response(self, link: Link, is_new: bool) -> Dict:
        """Форматирование итогового ответа по схеме URLResponse"""

        return {
            'already_exists': not is_new,
            'short_code': link.short_code,
            'short_url': f'{self.base_url}{link.short_code}',
            'original_url': link.original_url,
            'clicks': link.clicks,
            'created_at': link.created_at.isoformat(),
            'message': 'Ссылка уже существует' if not is_new else 'Ссылка успешно создана',
            'last_accessed': link.last_accessed.isoformat() if link.last_accessed else None
        }

