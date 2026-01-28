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
    def __init__(self, code_generator=None, url_validator=None, base_url=None, cache_client=None, cache_ttl=None):
        self.generator = code_generator or HashBasedGenerator(
            code_length=BaseConfig.SHORT_CODE_LENGTH, 
            pepper=BaseConfig.SHORT_CODE_SECRET_PEPPER
        )
        self.url_validator=url_validator or UrlValidator()
        self.base_url = base_url or BaseConfig.BASE_LINK
        self.cache = cache_client
        self.cache_ttl = cache_ttl or BaseConfig.REDIS_CACHE_TTL
        self.cache_ttl_stats = BaseConfig.REDIS_CACHE_TTL_STATS
        self.bath_limit = BaseConfig.BATH_CREATE_LIMIT

        self.CACHE_PREFIX_REDIRECT = "redirect:"
        self.CACHE_PREFIX_HASH = "hash:"
        self.CACHE_KEY_STATS = "service_stats"

        logger.info(
            'LinkService_initialized',
            short_code_length=BaseConfig.SHORT_CODE_LENGTH,
            base_url=self.base_url,
            cache_enabled=self.cache is not None
        )
   
    def create_short_url(self, original_url: str) -> Dict:
        """
        Создание короткой URL

        Args:
            original_url (str): Оригинальная URL

        Returns:
            dict: Словарь с результатом
        """
        try:
            logger.info(
                'Начало создания короткиой ссылки',
                original_url=original_url[:50]
            )

            # 1. Валидация и нормализация url
            is_valid, url_or_message = self.url_validator.is_valid_url(original_url)
            if not is_valid:
                logger.warning(
                    'Невалидный URL',
                    original_url=original_url,
                    validation_error=url_or_message
                )
                raise ValidationError(url_or_message, 'INVALID_URL')
            
            logger.debug('URL нормализован', normalized_url=url_or_message)

            # Генерация хэша для дедупликации и кода
            url_hash = self.generator.calculate_deduplication_hash(url_or_message)
            
            # 2. Проверка кэша по хэшу Url на дедупликацию
            cache_key_hash = f'{self.CACHE_PREFIX_HASH}{url_hash}'
            if self.cache:
                cashed_code_by_url_hash = self.cache.get(cache_key_hash)
                if cashed_code_by_url_hash:
                    logger.info('Найден код ссылки в кэше дедупликации')
                    existing_url = URLCrud.get_by_short_code(cashed_code_by_url_hash)
                    return self._format_url_response(existing_url, False)

            # 3. Генерация короткого кода для ссылки
            short_code = self.generator.generate_code(url_or_message)
            logger.debug(
                'hash_and_code_generated',
                url_hash=url_hash[:10],
                short_code=short_code
            )

            # 4. Сохранение в бд или получение, если уже существует запись с таким хэшем
            logger.debug('Запись нового элемента в базу данных...')
            short_url, is_created = URLCrud.create_or_get(
                source_url=original_url,
                url_hash=url_hash,
                short_code=short_code
            )

            # 5. Кэширование короткого кода для дедупликации (hash: short_code)
            if self.cache:
                is_cached_by_url_hash = self.cache.set(cache_key_hash, short_code, ttl=self.cache_ttl)
                
                if is_cached_by_url_hash:
                    logger.info(
                        'Данные ссылки успешно закэшированы',
                        redis_key=cache_key_hash
                    )
                else:
                    logger.warning(
                        'Возникли проблемы с кэшированием данных',
                        short_code=short_code,
                        url=url_or_message
                    )
            
            # 6. Формирование ответа
            response = self._format_url_response(short_url, is_created)

            if is_created:
                logger.info(
                    'Новая короткая ссылка успешно создана',
                    short_code=short_code,
                    original_url=url_or_message[:50]
                )
            else:
                logger.info(
                    'Найдена существующая ссылка',
                    short_code=short_code,
                    clicks_count=short_url.clicks
                )

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
                "Внутренняя ошибка при создании короткой ссылки",
                "SERVICE_ERROR"   
            )
    
    def get_original_url_for_refirect(self, short_code: str) -> str:
        """Получение оригинального url для редиректа"""
        try:
            logger.info('Начало редиректа короткому коду', short_code=short_code)

            # 1. Проверка кэша редиректа
            cache_key_redirect = f'{self.CACHE_PREFIX_REDIRECT}{short_code}'
            if self.cache:
                cached_url = self.cache.get(cache_key_redirect)
                if cached_url:
                    logger.debug(
                        'Ссылка найдена в кэше',
                        short_code=short_code,
                        cached_url=cached_url
                    )

                    # Обновление счетчика переходов по ссылке в базе данных
                    is_updated = URLCrud.increment_clicks(short_code)
                    if is_updated:
                        logger.debug('Счетчик перехода по ссылке обновлен')
                    else:
                        logger.warning(
                            'Не дуалось обновить счетчик перехода по ссылке',
                            short_code=short_code
                        )
                    return cached_url
            
            # 2. Извлечение из БД если нет данных в кэше
            logger.debug('Поиск кода в Базе данных...', short_code=short_code)

            element = URLCrud.get_by_short_code(short_code, increment_click=True)
            
            if not element:
                logger.warning('Запись в базе данных не найдена', short_code=short_code)
                raise NotFoundError(
                    f'Ссылка c кодом {short_code} не найдена', 
                    'URL_NOT_FOUND'
                )
            
            logger.debug(
                'Ссылка найдена в базе данных',
                short_code=short_code,
                original_url=element.original_url[:50],
                clicks_count=element.clicks
            )

            # 3. Кэширование для будущих редиректов
            if self.cache:
                is_cached = self.cache.set(cache_key_redirect, element.original_url, self.cache_ttl)
                if is_cached:
                    logger.debug('Ссылка успешно закэширована', redis_key=cache_key_redirect)
                else:
                    logger.warning(
                        'Возникли проблемы с кэшированием ссылки',
                        short_code=short_code
                    )
            

            logger.info(
                'Ссылка для редиректа получена',
                short_code=short_code,
                original_url=element.original_url[:50]
            )
            return element.original_url
            
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
            raise ServiceError(
                'Внутрення ошибка при получении ссылки для редиректа',
                'SERVICE_ERROR'
            )

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
            logger.debug('Поиск ссылки по коду в Базе данных...', short_code=short_code)
            element = URLCrud.get_by_short_code(short_code, increment_click=False)

            if not element:
                logger.warning('запись в базе данных не найдена')
                raise NotFoundError(
                    f'Короткая ссылка c {short_code} не найдена', 
                    'URL_NOT_FOUND'
                )

            logger.info(
                'Информация о ссылке найдена',
                short_code=short_code,
                url_hash=element.url_hash[:10],
                original_url=element.original_url[:50],
                clicks_count=element.clicks,
                from_cache=False
            )

            return {
                'url_hash': element.url_hash,
                'short_code': short_code,
                'short_url': f'{self.base_url}{short_code}',
                'original_url': element.original_url,
                'clicks': element.clicks,
                'created_at': element.created_at.isoformat(),
                'last_accessed': element.last_accessed.isoformat() if element.last_accessed else None,
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
            raise ServiceError(
                'Внутрення ошибка при получении информации о ссылке',
                'SERVICE_ERROR'
            )
    
    def batch_create(self, urls: List[str]) -> List[Dict]:
        """
        Пакетное создание ссылок

        Args:
            urls (List[str]): Список URL

        Returns:
            List[Dict]: Список созданных URL согласно схеме BatchURLSResponse
        """
        try:
            logger.info(
                'Начато пакетное создание ссылок', 
                urls_count=len(urls),
                batch_limit=self.bath_limit
            )

            if len(urls) > self.bath_limit:
                logger.warning(
                    'Превышен лимит допустимого пакетного создания, ' \
                    'длинну урезаем до лимита: '
                    f'{len(urls)} > {self.bath_limit}'
                )
                # Урезаем список ссылок до лимита
                urls = urls[:self.bath_limit]

            # Массив с созданными ссылками и ошибочными при валидации
            results = []
            invalid_count = 0
            error_count = 0

            # Подготовка данных и проверка дедупликации
            hash_to_data_url = {}
            hashes_to_check = []

            # 1. Валидация ссылок
            logger.debug('Инициализирован этап валидации URLs')

            for url in urls:
                
                # 1.1 Валидация
                is_valid, url_or_message = self.url_validator.is_valid_url(url)
                if not is_valid:
                    
                    logger.warning(
                        'Невалидный URL в пакете', 
                        original_url=url, 
                        error=url_or_message
                    )

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
                
                hash_to_data_url[url_hash] = {
                    'url_hash': url_hash,
                    'original_url': url,
                    'short_code': short_code
                }
                hashes_to_check.append(url_hash)

            
            logger.debug(
                'Этап валидации завершен',
                total_validated=len(hash_to_data_url),
                invalid_count=invalid_count,
                error_count=error_count #  TODO added later
            )

            # 2. Пакетная проверка дедупликации в кэше и Базе данных
            logger.debug('Инициализирован этап проверки дедупликации в кэше и бд')
            
            ## 2.1 Проверка в кэше
            existing_hashes = set()
            if self.cache and hashes_to_check:
                cache_keys = [f'{self.CACHE_PREFIX_HASH}{hash}' for hash in hashes_to_check]
                
                cached_results = self.cache.get_many(cache_keys)

                # Создаем набор существующих хэшей
                existing_hashes = {
                    url_hash
                    for url_hash, cache_key in zip(hashes_to_check, cache_keys)
                    if cached_results.get(cache_key)
                }
                
                logger.debug('Проверка в кэше завершена')
            
            ## 2.2 Проверка в бд для оставшихся хэшей не найденных в кэше

            # Отнимаем существующие хэши найденные в кэше
            hashes_to_check = [hash for hash in hashes_to_check if hash not in existing_hashes]
            
            if hashes_to_check: 
                existing_in_db = URLCrud.get_by_hashes(hashes_to_check)
                for data in existing_in_db:

                    existing_hashes.add(data.url_hash)
                    results.append({
                        'success': True,
                        'already_exists': True,
                        'source_url': data.original_url,
                        'short_url': f'{self.base_url}{data.short_code}',
                        'short_code': data.short_code,
                    })
                logger.debug('Проверка в БД завершена')
            
            logger.debug('Этап проверки дедупликации завершен')
            
            # Снова отнимаем существующие хэши найденные в Базе Данных
            hashes_to_check = [hash for hash in hashes_to_check if hash not in existing_hashes]

            # Подготовка списка новых URL для пакетного сохранения в БД
            new_urls_data = [
                {
                    'url_hash': hash,
                    'original_url': data['original_url'],
                    'short_code': data['short_code']
                }
                for hash, data in ((hash, hash_to_data_url[hash]) for hash in hashes_to_check)
            ]

            # 3. Пакетное сохранение в БД
            if new_urls_data:
                
                logger.debug(
                    'Инициализирован этап пакетного сохранения ссылок в базу данных',
                    record_count=len(new_urls_data)
                )
                
                created_urls = URLCrud.bulk_create(new_urls_data)

                logger.debug(
                    'Этап пакетного сохранения ссылок в базу данных завершен',
                    saved_records_count=len(created_urls)
                )

                for url in created_urls:
                    results.append(
                        {
                            'success': True,
                            'already_exists': False,
                            'source_url': url.original_url,
                            'short_url': f'{self.base_url}{url.short_code}',
                            'short_code': url.short_code,
                        }
                    )
            
            # 4. Кэширование результата сохранения в базу данных
            # TODO Реализовать кэширование записанных ссылок в базу данных
            # UPD: Пока не вижу смысла, может добавлю потом


            total_processed = len(results)
            success_count = sum(1 for item in results if item.get('success', False))
            failed_count = total_processed - success_count
            
            logger.info(
                'Пакетное создание завершено',
                total_processed=total_processed,
                success_count=success_count,
                failed_count=failed_count
            )

            # Формирование ответа
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
            raise ServiceError(
                'Внутрення ошибка пакетной генерации коротких ссылок',
                'SERVICE_ERROR'
            )
  
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
            stats = URLCrud.get_stats()
            
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

            logger.info(
                'Извлечена общая статистика сервиса',
                total_urls=total_urls,
                total_clicks=total_clicks,
                avg_clicks=avg_clicks
            )

            return result
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
    
    def cleanup_cache(self) -> Dict:
        """
        Очистка кэша
        """
        
        logger.info('Инициализирована очистка кэша')

        result = {
            'succes': False,
            'message': 'Кэш клиент не инициализирован',
            'cache_stats': None
        }
        if self.cache:
            try:
                # Получение статистики перед очисткой
                stats_before = self.cache.get_stats()

                clear_result = self.clear()

                stats_after = self.cache.get_stats()

                if clear_result:

                    result = {
                        'success': clear_result,
                        'message': 'Кэш успешно очищен',
                        'cache_stats': {
                            'before_cleanup': stats_before,
                            'after_cleanup': stats_after
                        }
                    }

                    logger.info(
                        'Кэш успешно очищен',
                        stats_before=stats_before,
                        stats_after=stats_after
                    )
                else:
                    result = {
                        'success': clear_result,
                        'message': 'Ошибка при отчистке кэша',
                        'cache_stats': {
                            'before_cleanup': stats_before,
                            'after_cleanup': stats_after
                        }
                    }
            except Exception as e:
                logger.error(
                    'Ошибка при отчистке кэша',
                    error=str(e),
                    error_type=type(e).__name__,
                    exc_info=True
                )
                result = {
                    'success': clear_result,
                    'message': 'Ошибка при отчистке кэша',
                    'cache_stats': {
                        'before_cleanup': stats_before,
                        'after_cleanup': stats_after
                    }
                }
        return result

    def _format_url_response(self, element: TableURL, created: bool) -> Dict:
        """Форматирование итогового ответа по схеме URLResponse"""

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

