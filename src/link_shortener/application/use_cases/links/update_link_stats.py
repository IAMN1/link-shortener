from dataclasses import dataclass
from link_shortener.domain import LinkRepository, ShortCode
from link_shortener.application.context import RequestContext
from link_shortener.application.ports.cache.link_cache import LinkCache
from link_shortener.application.ports.logger.logger import Logger
from link_shortener.application.use_cases.base_use_case import BaseUseCase


@dataclass
class UpdateLinkStatsUseCase(BaseUseCase):
    """
    Use case for asynchronously updating link statistics (click count).

    Designed to be called from a background worker (Celery). It increments
    the click counter, updates the last accessed timestamp, and refreshes
    the cache. No audit is performed here because audit is done synchronously
    in the redirect use case.
    """
    repository: LinkRepository
    link_cache: LinkCache
    logger: Logger

    def execute(self, short_code_str: ShortCode, context: RequestContext) -> None:
        """
        Update click count and cache for the given short code.

        Args:
            short_code_str: String representation of the short code.
            context: Request context (used for logging only, not for audit).
        """
        log = self._get_logger(self.logger, context)
        log.debug("Background task: updating link stats", short_code=short_code_str)

        try:
            short_code = ShortCode(short_code_str)

            # Сначала пробуем получить статистику из кэша
            link = self.link_cache.get_by_code(short_code)
            if not link:
                link = self.repository.find_by_code(short_code)
            
            if not link:
                log.warning("Link not found in background task", code=short_code_str)
                return
            
            # Увеличиваем счетчик кликов
            self.repository.increment_clicks(short_code)

            # Обновление кэша
            link.increment_clicks()
            self.link_cache.save(link)

            log.debug("Background stats updated", code=short_code_str, new_clicks=link.clicks)
        except Exception as e:
            log.error("Background task failed", short_code=short_code_str, error=str(e))