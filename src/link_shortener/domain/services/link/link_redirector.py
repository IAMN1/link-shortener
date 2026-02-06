from typing import Optional

from ....core.exceptions import NotFoundError

from ..base_service import BaseService
from ...interfaces.logger.abc_logger import ILogger
from ...interfaces.database.abc_repository import ILinkRepository
from ...services.cache.cache_manager import CacheManager
from ...value_objects.short_link_result import RedirectResult
from ...value_objects.cache_strategy import HashCacheStrategy, InfoCacheStrategy, RedirectCacheStrategy

class LinkRedirector(BaseService):
    """Доменный сервис для редиректов по коротким ссылкам."""

    def __init__(
        self,
        repository: ILinkRepository,
        cache_manager: Optional[CacheManager] = None,
        redirect_strategy: Optional[RedirectCacheStrategy] = None,
        hash_strategy: Optional[HashCacheStrategy] = None,
        info_strategy: Optional[InfoCacheStrategy] = None,
        cache_ttl: int = 3600,
        logger: Optional[ILogger] = None
    ):
        super().__init__(logger=logger)
        self._repository = repository
        self._cache_manager = cache_manager
        self._redirect_strategy = redirect_strategy
        self._hash_strategy = hash_strategy
        self._info_strategy = info_strategy
        self._cache_ttl = cache_ttl
    
    def get_original_url(self, short_code: str) -> RedirectResult:
        """
        Получает оригинальный URL для редиректа.
        
        Args:
            short_code: Короткий код ссылки
            
        Returns:
            RedirectResult: Результат редиректа
            
        Raises:
            NotFoundError: если ссылка не найдена
        """

        self._log_debug('получение оригинального URL', short_code=short_code)

        # 1. Проверка кэша
        if self._cache_manager and self._redirect_strategy:
            cached_url = self._cache_manager.get_link_by_short_code(short_code, self._redirect_strategy)

        if cached_url:
            self._log_info('URL найден в кэше', short_code=short_code)
            
            # обновление счетчика переходов по ссылке
            self._repository.increment_clicks(short_code)
            # or
            # Обновление кэшированных данных
            self._update_update_link_data(short_code)
            
            return RedirectResult(original_url=cached_url['original_url'], from_cache=True, clicks=None)
        

        # 2. Получение из репозитория
        link = self._repository.get_by_short_code(short_code)
        if not link:
            self._log_debug('Ссылка не найдена в базе данных', short_code=short_code)
            raise NotFoundError(f'Ссылка с кодом ({short_code}) не найдена')
        
        # 3. Инкремент счетчика перехода
        link.increment_clicks()
        self._repository.increment_clicks(short_code)

        # 4. Кэширование обновленных данных
        if self._cache_client:
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

    def _update_update_link_data(self, short_code: str) -> None:
        """Обновление кэшированных данных ссылки (в фоне)"""
        try:
            link = self._repository.get_by_short_code(short_code)
            if link and self._cache_manager:
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