from typing import Optional

from ..base_service import BaseService
from ...exceptions import LinkNotFoundError, ValidationError
from ...interfaces.utils.abc_code_extractor import IShortCodeExtractor
from ...interfaces.logger.abc_logger import ILogger
from ...interfaces.database.abc_repository import ILinkRepository
from ...services.cache.cache_manager import CacheManager
from ...value_objects.short_link_result import RedirectResult
from ...value_objects.cache_strategy import HashCacheStrategy, InfoCacheStrategy, RedirectCacheStrategy

class LinkRedirector(BaseService):
    """Доменный сервис для редиректов по коротким ссылкам."""

    def __init__(
        self,
        short_code_extractor:IShortCodeExtractor,
        repository: ILinkRepository,
        cache_manager: Optional[CacheManager] = None,
        redirect_strategy: Optional[RedirectCacheStrategy] = None,
        hash_strategy: Optional[HashCacheStrategy] = None,
        info_strategy: Optional[InfoCacheStrategy] = None,
        cache_ttl: int = 3600,
        logger: Optional[ILogger] = None
    ):
        super().__init__(logger=logger)
        self._code_extractor = short_code_extractor
        self._repository = repository
        self._cache_manager = cache_manager
        self._redirect_strategy = redirect_strategy
        self._hash_strategy = hash_strategy
        self._info_strategy = info_strategy
        self._cache_ttl = cache_ttl
    
    def extract_short_code(self, short_url: str) -> str:
        """
        Извлекает короткий код из сокращенной ссылки (бизнес-правило)
        
        Args:
            short_url: Сокращенная ссылка
            
        Returns:
            str: Короткий код
            
        Raises:
            ValidationError: Если ссылка имеет неверный формат
        """
        self._log_debug('Извлечение короткого кода из URL', short_url=short_url)

        # Проверка формата ссылки
        is_valid, error_message = self._code_extractor.validate_short_url_format(short_url)
        if not is_valid:
            self._log_warning('Неверный формат короткой ссылки', short_url=short_url, error=error_message)
            raise ValidationError(
                message=error_message,
                code='INVALID_SHORT_URL_FORMAT',
                field='short_url',
                value=short_url
            )
        
        # извелчение кода
        short_code = self._code_extractor.extract_code_from_url(short_url)
        if not short_code:
            self._logger.error('Неудалось извлечь код из ссылки', short_url=short_url)
            raise ValidationError(
                message='Не удалось извлечь короткий код из ссылки',
                code='SHORT_CODE_EXTRACTION_FAILED',
                field='short_url',
                value=short_url
            )
        
        self._log_debug('Код успешно извлечен', short_url=short_url, short_code=short_code)
        return short_code

    def get_original_url(self, short_url: str) -> RedirectResult:
        """
        Получает оригинальный URL для редиректа.
        
        Args:
            short_url: сокращенная ссылка
            
        Returns:
            RedirectResult: Результат редиректа
            
        Raises:
            ValidationError: если ссылка имеет неверный формат
            NotFoundError: если ссылка не найдена
        """

        self._log_debug('получение оригинального URL', short_url=short_url)

        # Извелечение кода из ссылки
        short_code = self.extract_short_code(short_url)

        # 1. Проверка кэша
        if self._cache_manager and self._redirect_strategy:
            cached_url = self._cache_manager.get_original_url(short_code, self._redirect_strategy)

            if cached_url:
                self._log_info('URL найден в кэше', short_code=short_code)
                
                # обновление счетчика переходов по ссылке в БД и кэше
                self._update_link_data(short_code)
                
                return RedirectResult(original_url=cached_url, from_cache=True, clicks=None)
        

        # 2. Получение из репозитория
        link = self._repository.get_by_short_code(short_code)
        if not link:
            self._log_warning('Ссылка не найдена в базе данных', short_code=short_code)
            raise LinkNotFoundError(short_code=short_code)
        
        # 3. Инкремент счетчика перехода
        link.increment_clicks()
        success = self._repository.increment_clicks(short_code)

        if not success:
            self._log_error('Не удалось обновить счетчик переходов', short_code=short_code)

        # 4. Кэширование обновленных данных
        if self._cache_manager:
            strategies = {}

            if self._redirect_strategy:
                strategies['redirect'] = self._redirect_strategy
            if self._hash_strategy:
                strategies['hash'] = self._hash_strategy
            if self._info_strategy:
                strategies['info'] = self._info_strategy
            
            if strategies:
                self._cache_manager.cache_link(link, strategies, self._cache_ttl)
            
        return RedirectResult(
            original_url=link.original_url,
            from_cache=False,
            clicks=link.clicks
        )

    def _update_link_data(self, short_code: str) -> None:
        """Обновление данных ссылки в бд и кэше после кэш-попадания."""
        try:
            link = self._repository.get_by_short_code(short_code)
            if link:
                link.increment_clicks()
                self._repository.increment_clicks(short_code)
                
                if self._cache_manager:
                    strategies = {}
                    if self._hash_strategy:
                        strategies['hash'] = self._hash_strategy
                    if self._info_strategy:
                        strategies['info'] = self._info_strategy
                    
                    if strategies:
                        self._cache_manager.cache_link(link, strategies, self._cache_ttl)
                        self._log_debug('Кэш успешно обновлен', short_code=short_code)
        
        except Exception as e:
            self._log_error('Ошибка при обновлении кэша', short_code=short_code, error=str(e))