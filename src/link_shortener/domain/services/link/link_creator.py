from typing import Optional

from ...exceptions import ValidationError
from ..cache.cache_manager import CacheManager
from ..base_service import BaseService
from ...value_objects.short_link_result import ShortLinkCreationResult
from ...entities.link import Link
from ...interfaces.database.abc_repository import ILinkRepository
from ...interfaces.logger.abc_logger import ILogger
from ...interfaces.utils.abc_code_generator import ICodeGenerator
from ...interfaces.utils.abc_url_validator import IUrlValidator
from ...value_objects.cache_strategy import HashCacheStrategy, RedirectCacheStrategy  

class ShortLinkCreator(BaseService):
    """Доменный сервис для создания коротких ссылок."""

    def __init__(
        self,
        repository: ILinkRepository,
        url_validator: IUrlValidator,
        code_generator: ICodeGenerator,
        cache_manager: Optional[CacheManager],
        hash_strategy: Optional[HashCacheStrategy] = None,
        redirect_strategy: Optional[RedirectCacheStrategy] = None,
        cache_ttl: int = 3600,
        logger: Optional[ILogger] = None
    ):
        super().__init__(logger=logger)
        self._repository = repository
        self._url_validator = url_validator
        self._code_generator = code_generator
        self._cache_manager = cache_manager
        self._hash_strategy = hash_strategy
        self._redirect_strategy = redirect_strategy
        self.cache_ttl = cache_ttl
    
    def create_short_url(self, original_url: str) -> ShortLinkCreationResult:
        """
        Создает короткую ссылку или возвращает существующую

        Args:
            original_url (str): Оригинальный URL для сокращения

        Returns:
            ShortLinkCreationResult: Результат сокращения
        
        Raises:
            ValidationError: Если Url не валидный
        """
        
        self._log_debug('Начало создания короткой ссылки', url=original_url[:50])

        # 1. Валидация URL (бизнес правило)
        is_valid, url_or_message = self._url_validator.is_valid_url(original_url)
        if not is_valid:
            self._log_warning('Невалидный URL', url=original_url, error=url_or_message)
            raise ValidationError(url_or_message,'INVALID_URL')
        
        normalized_url = url_or_message
        self._log_debug('Url нормализован', normalized_url=normalized_url[:50])

        # 2. генерация хэша для дедупликации
        url_hash = self._code_generator.calculate_deduplication_hash(normalized_url)
        self._log_debug('Хэш сгенерирован', hash=url_hash[:10])

        # 3. Поиск в хэше
        cached_link = None
        if self._cache_manager and self._hash_strategy:
            cached_link = self._cache_manager.get_link_by_hash(url_hash, self._hash_strategy)
        
        # 4. возврат из кэша, если нашли
        if cached_link:
            self._log_info('Ссылка найдена в кэше', short_code=cached_link.short_code)
            return ShortLinkCreationResult(
                link=cached_link,
                is_new=False,
                from_cache=True
            )
        
        # 5. Поиск в репозитории
        existing_link = self._repository.get_by_hash(url_hash)
        if existing_link:
            self._log_info('Ссылка найдена в базе данных', short_code=existing_link.short_code)
            
            # Кэширование найденной ссылки
            if self._cache_manager and self._hash_strategy and self._redirect_strategy:
                strategies = {
                    'hash': self._hash_strategy,
                    'redirect': self._redirect_strategy
                }
                self._cache_manager.cache_link(existing_link, strategies, self.cache_ttl)
            
            return ShortLinkCreationResult(
                link=existing_link,
                is_new=False,
                from_cache=False
            )
        
        # 6. Создание новой ссылки
        short_code = self._code_generator.generate_code(normalized_url)
        self._log_debug('Код сгенерирован', short_code=short_code)

        # 7. Создание доменной сущности
        link = Link.create(
            url_hash=url_hash,
            short_code=short_code,
            original_url=original_url
        )

        # 8. Сохранение в репозитории
        saved_link = self._repository.create(link)
        self._log_info('Ссылка создана', short_code=saved_link.short_code)

        # Кэширование новой ссылки
        if self._cache_manager and self._hash_strategy and self._redirect_strategy:
            strategies = {
                'hash': self._hash_strategy,
                'redirect': self._redirect_strategy
            }
            success = self._cache_manager.cache_link(saved_link, strategies, self.cache_ttl)

            if success:
                self._log_debug('Ссылка закэширована')
        
        return ShortLinkCreationResult(
            link=saved_link,
            is_new=True,
            from_cache=False
        )
