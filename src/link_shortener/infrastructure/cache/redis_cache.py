import json
from typing import Any, Dict, Optional, List
import redis
from domain.entities.link import Link

from application.ports.cache.link_cache import LinkCache
from domain.value_objects.short_code import ShortCode
from domain.value_objects.url_hash import UrlHash
from domain.value_objects.original_url import OriginalUrl
from src.link_shortener.application.ports.cache.link_service_stats_cache import StatsCache
from src.link_shortener.application.ports.cache.redirect_cache import RedirectCache
from src.link_shortener.infrastructure.cache.cache_key_generator import CacheKeyGenerator


class RedisLinkCache(LinkCache, RedirectCache, StatsCache):
    """
    Реализация кэша на Redis.

    - get_by_hash - для проверки на дедупликацию. 
        Вызывается при генерации ссылки.
    - get_by_hashes - Для проверки на дедупликацию.
        Вызывается при пакетной генерации ссылок.
    - get_original_url Для редиректа (L1 уровень)
    - get_by_code Для получения ссылки по коду (L2 уровень)

    - get_stats - Для получения статистики по сервису генерации сокращенных ссылок

    - get_cache_info - Для получения информации по использованию Redis кэша

    """
    
    def __init__(self, redis_url: str, config: Dict[str, Any]):
        self.client = redis.from_url(redis_url)
        self.config = config
        self.key_gen = CacheKeyGenerator(config)
        self.ttl = config.get("CACHE_LINK_TTL", 3600)
        self.stats_ttl = config.get("CACHE_STATS_TTL", 300)
    
    def _serialize(self, link: Link) -> bytes:
        """Сериализация ссылки для Redis"""
        data = {
            'id': link.id,
            'url_hash': link.url_hash.value,
            'short_code': link.short_code.value,
            'original_url': link.original_url.value,
            'created_at': link.created_at.isoformat(),
            'clicks': link.clicks,
            'last_accessed': link.last_accessed.isoformat() if link.last_accessed else None
        }
        return json.dumps(data).encode('utf-8')
    
    def _deserialize(self, data: bytes) -> Optional[Link]:
        """Десериализация ссылки из Redis"""
        from datetime import datetime
        
        try:
            data_dict = json.loads(data.decode('utf-8'))
            
            last_accessed = None
            if data_dict.get('last_accessed'):
                last_accessed = datetime.fromisoformat(data_dict['last_accessed'])
            
            return Link(
                id=data_dict['id'],
                url_hash=UrlHash(data_dict['url_hash']),
                short_code=ShortCode(data_dict['short_code']),
                original_url=OriginalUrl(data_dict['original_url']),
                created_at=datetime.fromisoformat(data_dict['created_at']),
                clicks=data_dict['clicks'],
                last_accessed=last_accessed
            )
        except Exception:
            return None
    
    def get_cache_info(self) -> Dict[str, Any]:
        """Получение информации об использовании кэша"""
        info = self.client.info()
        
        return {
            'used_memory': info.get('used_memory_human', 'N/A'),
            'connected_clients': info.get('connected_clients', 0),
            'uptime': info.get('uptime_in_seconds', 0),
            'keyspace_hits': info.get('keyspace_hits', 0),
            'keyspace_misses': info.get('keyspace_misses', 0),
        }
    
    # ========== LinkCache ==========
    def get_by_code(self, short_code: ShortCode) -> Optional[Link]:
        """Получить ссылку по короткому коду"""
        key = self.key_gen.for_short_code(short_code.value)
        data = self.client.get(key)
        
        return self._deserialize(data) if data else None

    def get_by_hash(self, url_hash: UrlHash) -> Optional[Link]:
        """Получить ссылку по хэшу URL"""
        key = self.key_gen.for_url_hash(url_hash.value)
        data = self.client.get(key)
        
        return self._deserialize(data) if data else None

    def get_by_hashes(self, url_hashes: List[UrlHash]) -> Dict[UrlHash, Optional[Link]]:
        """Получить несколько ссылок по хэшам"""

        keys = [self.key_gen.for_url_hash(h.value) for h in url_hashes]
        data_list = self.client.mget(keys)
        
        result = {}
        for url_hash, data in zip(url_hashes, data_list):
            result[url_hash] = self._deserialize(data) if data else None
        
        return result
    
    def save(self, link: Link) -> None:
        """Кэширование ссылки на всех уровнях"""
        # Сохраняем по нескольким ключам для быстрого поиска
        hash_key = self.key_gen.for_url_hash(link.url_hash.value)
        code_key = self.key_gen.for_short_code(link.short_code.value)
        redirect = self.key_gen.for_redirect(link.short_code.value)

        data = self._serialize(link)
        
        pipeline = self.client.pipeline()
        pipeline.setex(hash_key, self.ttl, data)
        pipeline.setex(code_key, self.ttl, data)
        pipeline.setex(redirect, self.ttl, link.original_url.value)
        pipeline.execute()
    
    def save_many(self, links: List[Link]) -> None:
        """Кэширование нескольких ссылок на всех уровнях"""
        pipeline = self.client.pipeline()
        
        for link in links:
            hash_key = self.key_gen.for_url_hash(link.url_hash.value)
            code_key = self.key_gen.for_short_code(link.short_code.value)
            redirect_key = self.key_gen.for_redirect(link.short_code.value)

            data = self._serialize(link)
            
            pipeline.setex(hash_key, self.ttl, data)
            pipeline.setex(code_key, self.ttl, data)
            pipeline.setex(redirect_key, self.ttl, link.original_url.value)
        
        pipeline.execute()
    
    def delete(self, short_code: ShortCode) -> None:
        """Удалить данных ссылки из кэша на всех уровнях"""

        code_key = self.key_gen.for_short_code(short_code.value)
        
        # Получение данных ссылки для создания ключей
        data = self.client.get(code_key)
        
        if not data:
            return
        
        link = self._deserialize(data)

        # Генерация ключей других уровней
        hash_key = self.key_gen.for_url_hash(link.url_hash.value)
        redirect_key = self.key_gen.for_redirect(short_code.value)
        
        # Полное удаление на всех уровнях
        pipeline = self.client.pipeline()
        pipeline.delete(hash_key)
        pipeline.delete(code_key)
        pipeline.delete(redirect_key)
        
        pipeline.execute()
    
    # ========== RedirectCache ==========
    def get_original_url(self, short_code: ShortCode) -> Optional[str]:
        """Получить оригинальный URL для редиректа"""
        key = self.key_gen.for_redirect(short_code.value)
        data = self.client.get(key)
        
        return data.decode('utf-8') if data else None
    
    def save_original_url(self, short_code: ShortCode, original_url: str) -> None:
        """Сохранить оригинальный URL для быстрого редиректа"""
        key = self.key_gen.for_redirect(short_code.value)
        self.client.setex(key, self.ttl, original_url)

    # ========== StatsCache ==========
    def get_stats(self) -> Optional[Dict[str, Any]]:
        """Получить статистику сервиса"""
        key = self.key_gen.for_stats()
        data = self.client.get(key)
        
        return json.loads(data.decode('utf-8')) if data else None
    
    def save_stats(self, stats: Dict[str, Any]) -> None:
        """Сохранить статистику сервиса"""
        key = self.key_gen.for_stats()
        data = json.dumps(stats)
        self.client.setex(key, self.stats_ttl, data)
    
    def delete_stats(self) -> None:
        """Удалить статистику"""
        key = self.key_gen.for_stats()
        self.client.delete(key)
