import json
import time
from typing import Any, Dict, List, Optional

from link_shortener.application import LinkCache, RedirectCache, StatsCache
from link_shortener.domain import Link, OriginalUrl, ShortCode, UrlHash
from link_shortener.infrastructure.cache.cache_key_generator import \
    CacheKeyGenerator
import redis
import logging


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

    def __init__(
        self, redis_url: str, prefix: str, link_ttl: int = 3600, stats_ttl: int = 300
    ):
        self.redis_url = redis_url
        self.key_gen = CacheKeyGenerator(prefix=prefix)
        self.ttl = link_ttl
        self.stats_ttl = stats_ttl

        # Internal state for failover
        self._client = None
        self._available = False
        self._last_attempt = 0.0
        self._retry_internal = 10

        self._connect()

    def _connect(self):
        """Initial connection attempt"""
        try:
            self._client = redis.from_url(
                self.redis_url, socket_connect_timeout=2, socket_timeout=2
            )
            self._client.ping()
            self._available = True
            
            logging.getLogger(__name__).info(
                "Redis connected successfully."
            )
        except redis.RedisError as e:
            logging.getLogger(__name__).error(
                f"Redis connection failed: {e}. Running without cache."
            )
            self._available = False
            self._client = None
    
    def _ensure_connection(self) -> bool:
        """
        Check if connection is alive 
        if not, attempt to reconnect if retry interval elapsed.
        Returns True if available.
        """
        if self._client is not None:
            try:
                self._client.ping()
                self._available = True
                return True
            except redis.RedisError:
                self._available = False

        if self._available:
            self._available = False
            self._last_attempt = time.time()
            return False
        
        if time.time() - self._last_attempt > self._retry_internal:
            try:
                self._client = redis.from_url(
                    self.redis_url, socket_connect_timeout=2, socket_timeout=2
                )
                self._client.ping()
                self._available = True

                logging.getLogger(__name__).info("Redis connection restored.")
                return True
            
            except redis.RedisError:
                self._last_attempt = time.time()
                return False
        return False

    def _execute(self, func, *args, **kwargs):
        """Execute a Redis operation, return None on failure."""
        if not self._ensure_connection():
            return None
        try:
            return func(*args, **kwargs)
        except redis.RedisError as e:
            
            logging.getLogger(__name__).error(f"Redis operation failed: {e}")
            
            self._available = False
            
            return None

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------
    def _serialize(self, link: Link) -> bytes:
        """Сериализация ссылки для Redis"""
        data = {
            "id": link.id,
            "url_hash": link.url_hash.value,
            "short_code": link.short_code.value,
            "original_url": link.original_url.value,
            "created_at": link.created_at.isoformat(),
            "clicks": link.clicks,
            "last_accessed": (
                link.last_accessed.isoformat() if link.last_accessed else None
            ),
        }
        return json.dumps(data).encode("utf-8")

    def _deserialize(self, data: bytes) -> Optional[Link]:
        """Десериализация ссылки из Redis"""
        from datetime import datetime

        try:
            data_dict = json.loads(data.decode("utf-8"))

            last_accessed = None
            if data_dict.get("last_accessed"):
                last_accessed = datetime.fromisoformat(data_dict["last_accessed"])

            return Link(
                id=data_dict["id"],
                url_hash=UrlHash(data_dict["url_hash"]),
                short_code=ShortCode(data_dict["short_code"]),
                original_url=OriginalUrl(data_dict["original_url"]),
                created_at=datetime.fromisoformat(data_dict["created_at"]),
                clicks=data_dict["clicks"],
                last_accessed=last_accessed,
            )
        except Exception:
            return None

    # ------------------------------------------------------------------
    # General methods
    # ------------------------------------------------------------------
    def get_cache_info(self) -> Dict[str, Any]:
        """Получение информации об использовании кэша"""
        info = self.client.info()

        return {
            "used_memory": info.get("used_memory_human", "N/A"),
            "connected_clients": info.get("connected_clients", 0),
            "uptime": info.get("uptime_in_seconds", 0),
            "keyspace_hits": info.get("keyspace_hits", 0),
            "keyspace_misses": info.get("keyspace_misses", 0),
        }

    # ------------------------------------------------------------------
    # LinkCache methods
    # ------------------------------------------------------------------
    def get_by_code(self, short_code: ShortCode) -> Optional[Link]:
        """Получить ссылку по короткому коду"""
        key = self.key_gen.for_short_code(short_code.value)
        data = self._execute(self._client.get, key)

        return self._deserialize(data) if data else None

    def get_by_hash(self, url_hash: UrlHash) -> Optional[Link]:
        """Получить ссылку по хэшу URL"""
        key = self.key_gen.for_url_hash(url_hash.value)
        data = self._execute(self._client.get, key)

        return self._deserialize(data) if data else None

    def get_by_hashes(self, url_hashes: List[UrlHash]) -> Dict[UrlHash, Optional[Link]]:
        """Получить несколько ссылок по хэшам"""

        keys = [self.key_gen.for_url_hash(h.value) for h in url_hashes]
        data_list = self._execute(self._client.mget, keys) or []

        result = {}
        for url_hash, data in zip(url_hashes, data_list):
            result[url_hash] = self._deserialize(data) if data else None

        return result

    def save(self, link: Link) -> None:
        """Кэширование ссылки на всех уровнях"""
        if not self._ensure_connection():
            return
        try:
            # Сохраняем по нескольким ключам для быстрого поиска
            hash_key = self.key_gen.for_url_hash(link.url_hash.value)
            code_key = self.key_gen.for_short_code(link.short_code.value)
            redirect = self.key_gen.for_redirect(link.short_code.value)

            data = self._serialize(link)

            pipeline = self._client.pipeline()
            
            pipeline.setex(hash_key, self.ttl, data)
            pipeline.setex(code_key, self.ttl, data)
            pipeline.setex(redirect, self.ttl, link.original_url.value)
            
            pipeline.execute()
        
        except redis.RedisError as e:
            logging.getLogger(__name__).error(f"Redis save failed: {e}")
            self._available = False

    def save_many(self, links: List[Link]) -> None:
        """Кэширование нескольких ссылок на всех уровнях"""
        
        if not links or not self._ensure_connection():
            return
        
        try:
            pipeline = self._client.pipeline()

            for link in links:
                hash_key = self.key_gen.for_url_hash(link.url_hash.value)
                code_key = self.key_gen.for_short_code(link.short_code.value)
                redirect_key = self.key_gen.for_redirect(link.short_code.value)

                data = self._serialize(link)

                pipeline.setex(hash_key, self.ttl, data)
                pipeline.setex(code_key, self.ttl, data)
                pipeline.setex(redirect_key, self.ttl, link.original_url.value)

            pipeline.execute()

        except redis.RedisError as e:
            logging.getLogger(__name__).error(f"Redis save_many failed: {e}")
            self._available = False

    def delete(self, short_code: ShortCode) -> None:
        """Удалить данных ссылки из кэша на всех уровнях"""

        if not self._ensure_connection():
            return
        
        try:
            code_key = self.key_gen.for_short_code(short_code.value)
            redirect_key = self.key_gen.for_redirect(short_code.value)

            # try to get link to find hash key
            data = self._execute(self._client.get, code_key)
            keys_to_delete = [code_key, redirect_key]
            if data:
                link = self._deserialize(data)
                if link:
                    keys_to_delete.append(
                        self.key_gen.for_url_hash(
                            link.url_hash.value
                        )
                    )
            self._client.delete(*keys_to_delete)
        except redis.RedisError as e:
            logging.getLogger(__name__).error(f"Redis delete failed: {e}")
            self._available = False

    # ------------------------------------------------------------------
    # RedirectCache methods
    # ------------------------------------------------------------------
    def get_original_url(self, short_code: ShortCode) -> Optional[str]:
        """Получить оригинальный URL для редиректа"""
        key = self.key_gen.for_redirect(short_code.value)
        
        data = self._execute(self._client.get, key)

        return data.decode("utf-8") if data else None

    def save_original_url(self, short_code: ShortCode, original_url: str) -> None:
        """Сохранить оригинальный URL для быстрого редиректа"""
        if not self._ensure_connection():
            return
        
        try:
            key = self.key_gen.for_redirect(short_code.value)
            self._client.setex(key, self.ttl, original_url)
        except redis.RedisError as e:
            logging.getLogger(__name__).error(
                f"Redis save_original_url failed: {e}"
            )
            
            self._available = False

    # ------------------------------------------------------------------
    # StatsCache methods
    # ------------------------------------------------------------------
    def get_stats(self) -> Optional[Dict[str, Any]]:
        """Получить статистику сервиса"""
        key = self.key_gen.for_stats()
        
        data = self._execute(self._client.get, key)

        return json.loads(data.decode("utf-8")) if data else None

    def save_stats(self, stats: Dict[str, Any]) -> None:
        """Сохранить статистику сервиса"""
        if not self._ensure_connection():
            return
        
        try:
            key = self.key_gen.for_stats()
            
            data = json.dumps(stats)
            
            self._client.setex(key, self.stats_ttl, data)

        except redis.RedisError as e:
            logging.getLogger(__name__).error(f"Redis save_stats failed: {e}")
            self._available = False

    def delete_stats(self) -> None:
        """Удалить статистику"""
        if not self._ensure_connection():
            return
        
        try:
            key = self.key_gen.for_stats()
            self._client.delete(key)

        except redis.RedisError as e:
            logging.getLogger(__name__).error(f"Redis delete_stats failed: {e}")
            self._available = False
