from dataclasses import dataclass
import threading
from typing import Optional


from link_shortener.application.ports.cache.link_cache import LinkCache
from link_shortener.application.ports.cache.redirect_cache import RedirectCache
from link_shortener.application.ports.logger.audit import AuditLogger
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.domain import LinkNotFoundError, LinkRepository, ShortCode


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
    logger: Logger
    audit_logger: AuditLogger

    def execute(self, short_code_str: str, user_ip: Optional[str] = None, user_agent: Optional[str] = None) -> str:
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
            # Создание VO с валидацией
            short_code = ShortCode(short_code_str)

            self.logger.debug("Redirect requested for", code=short_code.value)

            # 1. L1 кэш - только URL
            cached_url = self.redirect_cache.get_original_url(short_code)
            if cached_url:
                self.logger.info("Redirect cache hit (L1)", code=short_code.value)
                
                self._audit_and_update_async(short_code, user_ip, user_agent)
                
                return cached_url

            # 2. L2 кэш - (полная ссылка)
            cached_link = self.link_cache.get_by_code(short_code)
            if cached_link:
                self.logger.info(
                    "Link cache hit for redirect (L2)", code=short_code.value
                )

                # Сохранение в быстрый кэш для будущих запросов
                orig_url = cached_link.original_url.value
                self.redirect_cache.save_original_url(short_code, orig_url)

                self._audit_and_update_async(short_code, user_ip, user_agent)

                return orig_url

            # 3. Получение из репозитория
            link = self.repository.find_by_code(short_code)
            if not link:
                self.logger.warning(
                    "Link not found for redirect:", code=short_code.value
                )
                raise LinkNotFoundError(short_code_str)

            orig_url = str(link.original_url.value)

            # 4. Увеличение счетчика переходов по ссылке
            link.increment_clicks()
            self.repository.increment_clicks(short_code)

            # 5. Кэширование на всех уровнях
            self.link_cache.save(link)

            self.logger.info(
                "Redirect successful", code=short_code.value, url=orig_url[:50]
            )

            self.audit_logger.log_url_accessed(link, user_ip, user_agent)

            return orig_url

        except ValueError as e:
            self.logger.error(
                "Invalid short code format", code=short_code_str, error=str(e)
            )
            raise ValueError(f"Invalid short code: {str(e)}")

        except LinkNotFoundError:
            raise

        except Exception as e:
            self.logger.exception(
                "Error during redirect",
                exc_info=str(e),
                short_code=short_code_str,
            )
            raise RuntimeError(f"Failed to redirect: {str(e)}")

    def _audit_and_update_async(
        self, short_code: ShortCode, user_ip: Optional[str], user_agent: Optional[str]
    ) -> None:
        """
        Perform audit and click increment in background.
        TODO: Replace with proper async task queue (Celery) later.
        """
        def task():
            try:
                link = self.link_cache.get_by_code(short_code)
                if not link:
                    link = self.repository.find_by_code(short_code)
                
                if link:
                    self.audit_logger.log_url_accessed(link, user_ip, user_agent)
                    
                    self.repository.increment_clicks(short_code)
                else:
                    self.logger.error(
                        "Background audit failed: link not found", 
                        code=short_code.value
                    )

                # (old version)
                # Инвалидация сылки их кэша, следующий запрос закэширует
                # self.link_cache.delete(short_code)

                # кэширование (обновление)
                link.increment_clicks()
                self.link_cache.save(link)


                self.logger.debug(
                    "Background click increment completed",
                    short_code=short_code.value,
                    new_clicks=link.clicks,
                )
                self.logger.debug(
                    "Background audit completed",
                    short_code=short_code.value,
                    new_clicks=link.clicks,
                )

            except Exception as e:
                self.logger.error(
                    "Background click increment failed",
                    short_code=short_code.value,
                    error=str(e),
                )
                self.logger.error(
                    "Background audit failed",
                    short_code=short_code.value,
                    error=str(e),
                )
        thread = threading.Thread(target=task)
        thread.daemon = True
        thread.start()
