import structlog

from link_shortener.domain.events.link_events import UrlAccessed, UrlCreated


class AuditLogger:
    def __init__(self):
        self._logger = structlog.get_logger('audit')
    

    def log_url_created(self, event: UrlCreated):
        self._logger.info(
            'url_created',
            url_hash=event.url_hash,
            short_code=event.short_code,
            original_url=self._mask_url(event.original_url),
            is_new=event.is_new,
            
            user_ip=event.user_ip,
            timestamp=event.timestamp.isoformat(),
            event_type='URL_CREATED'
        )
    
    def log_url_accessed(self, event: UrlAccessed):
        self.logger.info(
            'url_accessed',
            short_code=event.short_code,
            original_url=self._mask_url(event.original_url),
            clicks=event.current_clicks,
            
            user_ip=event.user_ip,
            user_agent=event.user_agent,
            timestamp=event.timestamp.isoformat(),
            event_type='URL_ACCESSED'
        )

    def _mask_url(self, url: str) -> str:
        """Маскировака чувствительных данных ссылки для логов"""
        if len(url) > 100:
            return f'{url[:50]}...{url[-20:]}'
        return url