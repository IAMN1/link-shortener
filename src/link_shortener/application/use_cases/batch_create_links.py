from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional



from ..dtos.responses import BatchCreateResponse, BatchItemResponse
from ..ports.cache.link_cache import LinkCache
from ..ports.logger.logger import Logger
from domain.value_objects.short_code import ShortCode
from domain.value_objects.url_hash import UrlHash
from domain.entities.link import Link
from domain.policies.shortening_policy import ShorteningPolicy
from domain.repositories.link_repository import LinkRepository
from domain.value_objects.original_url import OriginalUrl


@dataclass
class BatchCreateLinksUseCase:
    """
    Use Case: Пакетное создание ссылок.
    """

    repository: LinkRepository
    cache: LinkCache
    shortening_policy: ShorteningPolicy
    logger: Optional[Logger]
    batch_limit: int = 100
    max_workers: int = 10 # not used, kept for compatibility

    def execute(self, urls: List[str]) -> BatchCreateResponse:
        """
        Основной сценарий использования.
        
        Args:
            urls: Список URL для сокращения
            
        Returns:
            BatchCreateResponse: Результаты пакетной обработки
            
        Raises:
            ValueError: Если превышен лимит пакета или URLs не валидны
        """
        if not urls:
            return BatchCreateResponse.empty()
        
        # 1. Проверки на лимит
        if len(urls) > self.batch_limit:
            if self.logger:
                self.logger.warning(
                    'Batch limit exceeded',
                    url_requested=len(urls),
                    limit=self.batch_limit
                )
            raise ValueError(
                f'Batch limit exceeded. Max: {self.batch_limit},\
                requested: {len(urls)}'
            )
        
        start_time = datetime.now()

        if self.logger:
            self.logger.info(
                'Starting batch link creation',
                urls_count=len(urls)
            )
        try:
            # 2. Группирование URL по хэшам для дедупликации
            url_groups = self._group_urls_by_hash(urls)
            
            if self.logger:
                self.logger.debug(
                    "URLs grouped by hash",
                    unique_hashes=len(url_groups),
                    total_urls=len(urls)
                )

            # 3. Batch-обработка групп
            batch_results = self._process_groups_batch(url_groups)

            # 4. Формирование итогового ответа
            response = BatchCreateResponse.from_results(batch_results)

            processing_time = (datetime.now() - start_time).total_seconds()
            urls_per_second=round(response.total / processing_time, 2) if processing_time > 0 else 0
            
            if self.logger:
                self.logger.info(
                    'Btach link creation completed',
                    total=response.total,
                    successful=response.successful,
                    failed=response.failed,
                    urls_per_second=urls_per_second,
                    cache_hits=response.from_cache_count,
                    db_hits=response.from_db_count
                )

            return response
        
        except Exception as e:
            if self.logger:
                self.logger.exception(
                    'Batch link creation failed',
                    url_count=len(urls),
                    error=str(e),
                )
            raise RuntimeError(f'Batch processing failed: {str(e)}')
    
    def _group_urls_by_hash(self, urls: List[str]) -> Dict[str, Dict]:
        """группирование URL по их хэшам"""
        
        groups = {}
        invalid_counter = 0

        for url in urls:
            try:
                # Валидация и создание VO
                original_url = OriginalUrl(url)
                
                # Вычисление хэша
                url_hash = self.shortening_policy.calculate_hash(original_url)
                hash_key = url_hash.value

                if hash_key not in groups:
                    groups[hash_key] = {
                        'hash': url_hash,
                        'original_url': original_url,
                        'urls': [],
                        'is_valid': True
                    }
                groups[hash_key]['urls'].append(url)
            
            except ValueError as e:

                error_key = f'invalid_{invalid_counter}'
                invalid_counter += 1

                # Добавление групп для невалидных URL
                groups[error_key] = {
                    'hash': None,
                    'original_url': None,
                    'urls': [url],
                    'is_valid': False,
                    'error': str(e)
                }

                if self.logger:
                    self.logger.warning(
                        'Invalid URL in batch',
                        url=url[:50],
                        error=str(e)
                    )

        return groups
    
    def _process_groups_batch(self, groups: Dict[str, Dict]) -> List[BatchItemResponse]:
        """Batch-обработка групп URL"""

        results = []

        # 1. разделение на валидные и невалидные группы
        valid_groups = []
        invalid_results = []

        for _, group in groups.items():
            if not group.get('is_valid', True):
                # Обработка невалидных групп
                erorr_msg = group.get('error', 'Invalid_url')
                for url in group['urls']:
                    invalid_results.append(BatchItemResponse.error_(
                        url=url,
                        error=erorr_msg
                    ))
            else:
                valid_groups.append(group)
        
        if not valid_groups:
            return invalid_results
        
        # 2. формирование списка хэшей для batch запроса к кэшу
        url_hashes = [group['hash'] for group in valid_groups]
        cached_links_map = self.cache.get_by_hashes(url_hashes)

        # 3. Определение групп, ненайденных в кэше
        groups_not_in_cache = []
        cache_results = []

        for group in valid_groups:
            url_hash = group['hash']
            cached_link = cached_links_map.get(url_hash)

            if cached_link:
                # найдено в кэше
                for url in group['urls']:
                    cache_results.append(BatchItemResponse.success(
                        url=url,
                        short_code=str(cached_link.short_code.value),
                        original_url=str(cached_link.original_url.value),
                        clicks=cached_link.clicks,
                        from_cache=True
                    ))
            else:
                groups_not_in_cache.append(group)
        
        if not groups_not_in_cache:

            results.extend(cache_results)
            results.extend(invalid_results)
            return results
        
        # 4. Batch запрос к БД для групп ненайденных в кэше
        missing_hashes = [group['hash'] for group in groups_not_in_cache]
        db_link_map = self.repository.find_by_hashes(missing_hashes)

        # 5. Определение групп, требующих создания новых ссылок
        groups_to_create = []
        db_results = []
        links_to_cache_from_db = []

        for group in groups_not_in_cache:
            url_hash = group['hash']
            db_link = db_link_map.get(url_hash)

            if db_link:
                # найдено в БД - добавляем в кэш
                links_to_cache_from_db.append(db_link)

                for url in group['urls']:
                    db_results.append(BatchItemResponse.success(
                        url=url,
                        short_code=str(db_link.short_code.value),
                        original_url=str(db_link.original_url.value),
                        clicks=db_link.clicks,
                        is_new=False
                    ))
            else:
                groups_to_create.append(group)
        
        if not groups_to_create:
            if links_to_cache_from_db:
                self.cache.save_many(links_to_cache_from_db)
            
            results.extend(cache_results)
            results.extend(db_results)
            results.extend(invalid_results)
            return results
        
        # 6. создание новых ссылок
        new_links = self._create_new_links_batch(groups_to_create)

        if not new_links:
            # В случае, если создание новых ссылок провалилось
            error_results = []
            for group in groups_to_create:
                for url in group['urls']:
                    error_results.append(BatchItemResponse.error_(
                        url=url,
                        error='Failed to create short URL'
                    ))

            results.extend(cache_results)
            results.extend(db_results)
            results.extend(error_results)
            results.extend(invalid_results)

            return results
        
        # 7. Batch сохранение новых ссылок в БД
        saved_links = self.repository.save_many(new_links)

        # 8. Batch кэширование всех новых ссылок
        links_to_cache = []
        links_to_cache.extend(links_to_cache_from_db)
        links_to_cache.extend(saved_links)

        if links_to_cache:
            self.cache.save_many(links_to_cache)
        
        # 9. Формирование результата для новых ссылок
        new_results = self._create_new_link_results(groups_to_create, saved_links)

        # 10. Объединение всех результатов
        results.extend(cache_results)
        results.extend(db_results)
        results.extend(new_results)
        results.extend(invalid_results)
        return results

    def _create_new_links_batch(self, groups: List[Dict]) -> List[Link]:
        """Пакетное создание новых ссылок с разрешением коллизий"""
        # 1. Генерация кодов для всех групп
        hash_to_code = {}

        for group in groups:
            original_url = group['original_url']
            short_code = self.shortening_policy.generate_code(original_url)
            hash_to_code[group['hash']] = short_code
        
        # 2. Проверка коллизий кодов одним Batch запросом
        unique_codes = list(set(hash_to_code.values()))
        existing_codes_map = self.repository.find_by_codes(unique_codes)

        # 3. Обработка возникших коллизий
        resolved_codes = self._resolve_collisions_batch(
            hash_to_code, existing_codes_map, groups
        )

        # 4. Создание доменных сущностей
        new_links = []
        for group in groups:
            url_hash = group['hash']
            original_url = group['original_url']
            short_code = resolved_codes.get(url_hash)

            if not short_code:
                # при неудаче разрешить коллизию
                continue
            new_link = Link.create(
                url_hash=url_hash,
                short_code=short_code,
                original_url=original_url
            )
            new_links.append(new_link)
        
        return new_links

    def _resolve_collisions_batch(
        self,
        hash_to_code: Dict[UrlHash, ShortCode],
        existing_codes_map: Dict[ShortCode, Optional[Link]],
        groups: List[Dict]
    ) -> Dict[UrlHash, ShortCode]:
        """Пакетное разрешение коллизий кодов"""
        resolved = {}
        collision_attempts = defaultdict(int)
        max_attempts = 5

        # Словарь для быстрого поиска группы по хэшу
        hash_to_group = {group['hash']: group for group in groups}

        # Очередь для обработки
        processing_queue = deque(hash_to_code.items())

        occupied_codes = set(existing_codes_map.keys())

        while processing_queue:
            url_hash, short_code = processing_queue.popleft()

            if short_code in occupied_codes:
                # Если код уже существует и не является текущей ссылкой
                existing_link = existing_codes_map.get(short_code)
                if existing_link and existing_link.url_hash != url_hash:
                    # Возникла коллизия, пытаемся сгенерировать новый код
                    attempt_key = (url_hash, short_code)
                    collision_attempts[attempt_key] += 1

                    if collision_attempts[attempt_key] > max_attempts:
                        # Превышено количество попыток = пропуск
                        continue
                    
                    # Генерация кода с добавленным суффиксом
                    group = hash_to_group[url_hash]
                    original_url = group['original_url']
                    attempt = collision_attempts[attempt_key]
                    suffixed_url = OriginalUrl(f'{original_url}#batch_{attempt}')

                    new_code = self.shortening_policy.generate_code(suffixed_url)

                    # Проверка нового кода
                    if new_code and new_code not in occupied_codes:
                        # В случае, если новый код не вызывает коллизию
                        resolved[url_hash] = new_code
                        occupied_codes.add(new_code)

                    else:
                        # При новой коллизии возвращение в очередь
                        processing_queue.append((url_hash, new_code))
                else:
                    # code exists but it's the same URL -> treat as resolved
                    resolved[url_hash] = short_code
                    occupied_codes.add(short_code)
            else:
                # Код является уникальным
                resolved[url_hash] = short_code
                occupied_codes.add(short_code)
        
        return resolved
    
    def _create_new_link_results(
        self,
        groups: List[Dict],
        saved_links: List[Link]
    ) -> List[BatchItemResponse]:
        """Создание результатов для новых ссылок"""
        results = []

        # Словарь для быстрого поиска ссылки по хэшу
        hash_to_link = {link.url_hash: link for link in saved_links}

        for group in groups:
            url_hash = group['hash']
            saved_link = hash_to_link.get(url_hash)

            if not saved_link:
                # Если ссылка не была сохранена
                for url in group['urls']:
                    results.append(BatchItemResponse.error_(
                        url=url,
                        error='Failed to save link'
                    ))
                continue

            # Первый URL в группе = новая ссылка
            results.append(BatchItemResponse.success(
                url=str(saved_link.original_url.value),
                short_code=str(saved_link.short_code.value),
                original_url=str(saved_link.original_url.value),
                clicks=saved_link.clicks,
                is_new=True
            ))

            # Остальные URL в группе = дубликаты первой ссылки
            for url in group['urls'][1:]:
                results.append(BatchItemResponse.success(
                    url=url,
                    short_code=str(saved_link.short_code.value),
                    original_url=str(saved_link.original_url.value),
                    clicks=saved_link.clicks,
                    is_new=False,
                    duplicate_of=str(saved_link.original_url.value)
                ))
        return results


    