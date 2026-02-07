
from itertools import chain
from typing import List, Optional, Tuple

from ...interfaces.database.abc_repository import ILinkRepository
from ...interfaces.logger.abc_logger import ILogger
from ...interfaces.utils.abc_code_generator import ICodeGenerator
from ...interfaces.utils.abc_url_validator import IUrlValidator
from ..cache.cache_manager import CacheManager
from ..base_service import BaseService
from ...entities.link import Link
from ...value_objects.cache_strategy import HashCacheStrategy, RedirectCacheStrategy
from ...value_objects.short_link_result import BatchLinkData, BatchProcessingSummary, BatchResultItem


class BatchLinkProcessor(BaseService):
    """Доменный сервис для пакетной обработки ссылок"""

    def __init__(
        self,
        repository: ILinkRepository,
        url_validator: IUrlValidator,
        code_generator: ICodeGenerator,
        cache_manager: Optional[CacheManager] = None,
        hash_strategy: Optional[HashCacheStrategy] = None,
        redirect_strategy: Optional[RedirectCacheStrategy] = None,
        cache_ttl: int = 3600,
        batch_limit: int = 100,
        logger: Optional[ILogger] = None
    ):
        super().__init__(logger)
        self._repository = repository
        self._url_validator = url_validator
        self._code_generator = code_generator
        self._batch_limit = batch_limit
        self._cache_manager = cache_manager
        self._hash_strategy = hash_strategy
        self._redirect_strategy = redirect_strategy
        self._cache_ttl = cache_ttl

    def batch_create(self, urls: List[str]) -> Tuple[List[BatchResultItem], BatchProcessingSummary]:
        """
        Пакетное создание коротких ссылок

        Args:
            urls (List[str]): Список оригинальных URL

        Returns:
            Tuple: (Результат обработки, сводка)
        """

        self._log_info('Начало пакетной обработки ссылок', urls_count=len(urls))

        if len(urls) > self._batch_limit:
            self._log_warning(
                'Превышен досутпный лимит ссылок для пакетной обработки!' \
                ' Список будет урезан до лимита',
                limit=self._batch_limit,
                requested_to_processing=len(urls)
            )
        urls = urls[:self._batch_limit]

        # подготовка данных
        validation_results = self._validate_and_prepare_urls(urls)

        # Группировка результатов
        valid_data = [r for r in validation_results if r.success]
        invalid_results = [r for r in validation_results if not r.success]

        if not valid_data:
            summary = BatchProcessingSummary(
                total=len(urls),
                successful=0,
                failed=len(urls),
                new=0,
                existing=0,
                from_cache=0
            )
            return invalid_results, summary
        
        # Обработка валидных URL
        processing_results = self._process_valid_urls([d.data for d in valid_data])

        # Обединение результатов
        all_res = invalid_results + processing_results

        # Формирование сводки
        summary = self._create_summary(all_res)

        self._log_info('Пакетная обработка завершена', summary=summary)

        return all_res, summary
    
    def _validate_and_prepare_urls(self, urls: List[str]) -> List[BatchResultItem]:
        """Валитдация и подготовка URL"""
        results = []

        for url in urls:
            try:
                is_valid, result = self._url_validator.is_valid_url(url)
                if not is_valid:
                    results.append(
                        BatchResultItem(
                            success=False,
                            data=BatchLinkData(url=url),
                            error=result,
                            is_new=None
                        )
                    )
                    continue
                
                normalized_url = result
                url_hash = self._code_generator.calculate_deduplication_hash(normalized_url)
                short_code = self._code_generator.generate_code(normalized_url)

                results.append(
                    BatchResultItem(
                        success=True,
                        data = BatchLinkData(
                            url=url,
                            url_hash=url_hash,
                            short_code=short_code
                        ),
                        is_new=True,
                        from_cache=False
                    )
                )
            except Exception as e:
                results.append(BatchResultItem(
                    success=False,
                    data=BatchLinkData(url=url),
                    error=f'Ошибка обработки: {str(e)}'
                ))

        return results
    
    def _process_valid_urls(self, valid_data: List[BatchLinkData]) -> List[BatchResultItem]:
        """
        Обработка валидации URL
        Проверяет валидные URL на наличии в кэше и базе данных
        """

        results = []
        # Группировка по хэшам
        hash_to_data = {data.url_hash: data for data in valid_data}

        # 1. Проверка в хэшей на наличие в кэше
        cached_links = self._check_cache_for_hashes(list(hash_to_data.keys()))

        # 2. Проверка в Базе данных для отсавшихся хэшей
        remaining_hashes = [
            h for h in hash_to_data.keys()
            if h not in [c.url_hash for c in cached_links]
        ]

        if remaining_hashes:
            db_links = self._repository.get_by_hashes(remaining_hashes)
        else:
            db_links = []
        
        # 3. Формирование результатов для найденных ссылок в кэше и базе данных
        for link in chain(cached_links, db_links):
            data = hash_to_data[link.url_hash]
            results.append(BatchResultItem(
                success=True,
                data=BatchLinkData(
                    url=data.url,
                    url_hash=data.url_hash,
                    short_code=data.short_code,
                    clicks=data.clicks
                ),
                is_new=False,
                from_cache=(link in cached_links)
            ))
            del hash_to_data[link.url_hash]
        
        # 4. Генерация новых ссылок
        created_links = []
        if hash_to_data:
            new_links_data = []
            for hash_, data in hash_to_data.items():
                new_links_data.append({
                    'url_hash': hash_,
                    'original_url': data.url,
                    'short_code': data.short_code
                })
            
            created_links = self._repository.bulk_create(new_links_data)

            for link in created_links:
                data = hash_to_data[link.url_hash]
                results.append(BatchResultItem(
                    success=True,
                    data=BatchLinkData(
                        url=data.url,
                        url_hash=data.url_hash,
                        short_code=data.short_code,
                        clicks=data.clicks
                    ),
                    is_new=True,
                    from_cache=False
                ))
            
        # Кэширование новых ссылок и ссылок из бд
        if self._cache_manager and self._hash_strategy and self._redirect_strategy:
            links_to_cache = []
            links_to_cache.extend(db_links)
            links_to_cache.extend(created_links)
            if links_to_cache:
                self._cache_new_links(links_to_cache)
        
        return results
    
    def _check_cache_for_hashes(self, url_hashes: List[str]) -> List[Link]:
        """проверка наличия ссылок в кэше"""
        if not self._cache_manager or not self._hash_strategy:
            return []
        return self._cache_manager.get_link_by_hashes(url_hashes, self._hash_strategy)
    
    def _cache_new_links(self, links: List[Link]) -> None:
        """Кэширование новых ссылок"""
        if not self._cache_manager or not links:
            return
        
        strategies = {}

        if self._hash_strategy:
            strategies['hash'] = self._hash_strategy
        if self._redirect_strategy:
            strategies['redirect'] = self._redirect_strategy
        
        if strategies:
            self._cache_manager.cache_links(links, strategies, self._cache_ttl)
    
    def _create_summary(self, results: List[BatchResultItem]) -> BatchProcessingSummary:
        """Создание сводки по резульатам операции пакетного создания ссылок"""
        total = len(results)
        successfull = sum(1 for r in results if r.success)
        failed = total - successfull
        new = sum(1 for r in results if r.success and r.is_new)
        existing = successfull - new
        from_cache = sum(1 for r in results if r.success and r.from_cache)

        return BatchProcessingSummary(
            total=total,
            successful=successfull,
            failed=failed,
            new=new,
            existing=existing,
            from_cache=from_cache
        )