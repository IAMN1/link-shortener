from dataclasses import dataclass

from link_shortener.application import LinkCache, Logger, RedirectCache
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
            # Создание VO с валидацией
            short_code = ShortCode(short_code_str)

            self.logger.debug("Redirect requested for", code=short_code.value)

            # 1. L1 кэш - только URL
            cached_url = self.redirect_cache.get_original_url(short_code)
            if cached_url:
                self.logger.info("Redirect cache hit (L1)", code=short_code.value)

                # Увеличение счетчика переходов по ссылке
                self._increment_clicks_sync(short_code)
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

                # Увеличение счетчика переходов
                self._increment_clicks_sync(short_code)

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

            return orig_url

        except ValueError as e:
            self.logger.error(
                "Invalid short code format", code=short_code.value, error=str(e)
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

    def _increment_clicks_sync(self, short_code: ShortCode) -> None:
        """Синхронное увеличение счетчика"""

        try:
            link = self.repository.find_by_code(short_code)
            if link:
                link.increment_clicks()
                self.repository.increment_clicks(short_code)

                # Обновление кэша
                self.link_cache.save(link)

                self.logger.debug(
                    "Background click increment completed",
                    short_code=short_code.value,
                    new_clicks=link.clicks,
                )

        except Exception as e:
            self.logger.error(
                "Background click increment failed",
                short_code=short_code.value,
                error=str(e),
            )
