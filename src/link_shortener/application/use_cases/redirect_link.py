from dataclasses import dataclass
from typing import Optional

from application.ports.cache.link_cache import LinkCache
from application.ports.cache.redirect_cache import RedirectCache
from application.ports.logger.logger import Logger
from domain.exceptions import LinkNotFoundError
from domain.repositories.link_repository import LinkRepository
from domain.value_objects.short_code import ShortCode


@dataclass
class RedirectLinkUseCase:
    """
    Use Case: Редирект по короткой ссылке

    Основной сценарий при использовании:
    1. Валидирует и нормализует код через VO
    2. Получение из кэша для редиректа (L1 уровень)
    3. Получение из общего кэша (L2, если не нашли в L1)
    4. Получение из репозитория (если не нашли в кэше)
    5. Увеличение счетчика переходов по ссылке
    6. Кэширование на всех уровнях
    """
    
    repository: LinkRepository
    link_cache: LinkCache
    redirect_cache: RedirectCache
    logger: Optional[Logger] = None

    def execute(self, short_code_str: str) -> str:
        """
        Основной сценарий использования.
        
        Args:
            short_code_str: Короткий код ссылки
            
        Returns:
            str: Оригинальный URL для редиректа
            
        Raises:
            LinkNotFoundError: Если ссылка не найдена
        """
        try:
            # 1. Создание VO с валидацией
            short_code = ShortCode(short_code_str)

            if self.logger:
                self.logger.debug('Redirect requested for', code=short_code.value)
            
            # 2. Попытка получить из кэша
            cached_url = self.redirect_cache.get_original_url(short_code)
            if cached_url:
                if self.logger:
                    self.logger.info(
                        'Redirect cache hit (L1)',
                        code=short_code
                    )

                # Асинхронное обновление счетчика переходов по ссылке
                self._async_increment_clicks(short_code)
                return cached_url
            
            # 3. Попытка получения из общего кэша ссылок L2
            cached_link = self.link_cache.get_by_code(short_code)
            if cached_link:
                if self.logger:
                    self.logger.info(
                        'Link cache hit for redirect (L2)',
                        code=short_code
                    )
                
                # Сохранение в быстрый кэш для будущих запросов
                orig_url = cached_link.original_url.value
                self.redirect_cache.save_original_url(short_code, orig_url)

                # Асинхронное обновление счетчика переходов
                self._async_increment_clicks(short_code)

                return orig_url
            
            # 4. получение из репозитория
            link = self.repository.find_by_code(short_code)
            if not link:
                if self.logger:
                    self.logger.warning(
                        'Link not found for redirect:',
                        code=short_code
                    )
                raise LinkNotFoundError(short_code_str)
            
            orig_url = str(link.original_url.value)
            
            # 5. Увеличение счетчика переходов по ссылке
            link.increment_clicks()
            self.repository.increment_clicks(short_code)

            # 6. Кэширование на всех уровнях
            self.link_cache.save(link)

            if self.logger:
                self.logger.info(
                    'Redirect successful',
                    code=short_code,
                    url=orig_url[:50]
                )
            
            return orig_url
        
        except ValueError as e:
            if self.logger:
                self.logger.error(
                    'Invalid short code format',
                    code=short_code,
                    error=str(e)
                )
            raise ValueError(f'Invalid short code: {str(e)}')
        
        except LinkNotFoundError:
            raise

        except Exception as e:
            if self.logger:
                self.logger.exception(
                    'Error during redirect',
                    short_code=short_code_str,
                    exc_info=str(e)
                )
            raise RuntimeError(f'Failed to redirect: {str(e)}')
    
    def _async_increment_clicks(self, short_code: ShortCode) -> None:
        """Асинхронное обновление счетчика переходов по ссылке"""
        # TODO Продумать вариант  
        # об использовании (Celery, RQ, etc) или асаинхронной задаче
        try:
            link = self.repository.find_by_code(short_code)
            if link:
                link.increment_clicks()
                self.repository.increment_clicks(short_code)

                # Обновление кэша
                self.link_cache.save(link)

                if self.logger:
                    self.logger.debug(
                        'Async click increment completed',
                        short_code=short_code.value,
                        new_clicks=link.clicks
                    )

        except Exception as e:
            if self.logger:
                self.logger.error(
                    'Failed to async increment clicks',
                    short_code=short_code.value,
                    error=str(e)
                )