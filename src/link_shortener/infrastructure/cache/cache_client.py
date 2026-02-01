import json
from typing import Any, Dict, List, Optional
from redis import ConnectionPool, Redis
from redis.exceptions import ConnectionError, TimeoutError, RedisError

from link_shortener.domain.intefaces.abc_cache import ICacheClient
from link_shortener.infrastructure.core.logging_config import get_logger


logger = get_logger(__name__)

class RedisCacheClient(ICacheClient):
    """
    Реализация клиента для работы с Redis кэшем
    Обеспечивает безопасное подключение, обработку ошибок и логирование

    Особенности клиента:
    1. Автоматическое переподключение при сбоях.
    2. Логирование всех операций.
    3. Обработка ошибок с fallback на БД.
    4. Поддержка разных форматов данных (JSON, pickle)
    """

    def __init__(self, config):
        self.config = config
        self._client = None
        self._connection_pool = None
        self._is_connected = False
    
        # Статистика использования кэша для мониоринга
        self.stats = {
            'hits': 0,
            'misses': 0,
            'errors': 0,
            'total_operations': 0
        }

        logger.info(
            'cache_client_initializing',
            redis_enabled=self.config.REDIS_ENABLED,
            redis_url=self._mask_redis_url(self.config.REDIS_URL)
        )

        if self.config.REDIS_ENABLED:
            self._connect()
    
    def _mask_redis_url(self, url: str) -> str:
        """
        Маскировка чувствительных данных в Url redis для логирования

        Args:
            url (str): Url redis

        Returns:
            str: masked url redis
        """
        if '@' in url:
            parts = url.split('@')
            auth_part = parts[0]
            if ':' in auth_part:
                # redis://username:password@host:port/db
                protocol, credentials = auth_part.split('://')
                if ':' in credentials:
                    user, pswd = credentials.split(':')
                    masked_auth=f'{protocol}://{user}:****@{parts[1]}'
                    return masked_auth
        return url
    
    def _connect(self):
        try:
            self._connection_pool = ConnectionPool.from_url(
                self.config.REDIS_URL,
                max_connections=20,
                socket_connection_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
                health_check_interval=30
            )

            self._client = Redis(connection_pool=self._connection_pool)

            # тестовый запрос для проверки соединения
            self._client.ping()
            self._is_connected = True

            logger.info(
                'redis_cache_connection_successful',
                redis_url=self._mask_redis_url(self.config.REDIS_URL)
            )

        except (ConnectionError, TimeoutError) as e:
            logger.error(
                'redis_cache_connection_failed',
                error=str(e),
                error_type=type(e).__name__,
                redis_url=self._mask_redis_url(self.config.REDIS_URL)
            )
            self._is_connected = False
            self._client = None
        
        except RedisError as e:
            logger.error(
                'cache_initialization_error',
                error=str(e),
                error_type=type(e).__name__,
                redis_url=self._mask_redis_url(self.config.REDIS_URL)
            )
            self._is_connected = False
            self._client = None

    def _ensure_connection(self) -> bool:
        """проверка соединения и переподключение при необходимости"""
        if not self.config.REDIS_ENABLED or not self._is_connected:
            return False
        
        try:
            if self._client:
                self._client.ping()
                return True
        except (ConnectionError, TimeoutError, RedisError):
            logger.warning('redis_cache_connection_lost_reconnecting')
            self._connect()
            return self._is_connected
    
    def _build_key(self, key: str) -> str:
        """Добавление префикса к ключу для изоляции приложения"""
        return f'{self.config.CACHE_PREFIX}{key}'
    
    def _serialize(self, value: Any) -> bytes:
        """Сериализация для хранения в Redis"""
        try:
            return json.dumps(value, ensure_ascii=False).encode('utf-8')
        except (TypeError, ValueError) as e:
            logger.error(
                'redis_cache_serialization_error',
                value_type=type(value).__name__,
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True
            )
            raise TypeError(
                f'Неудалось сериализовать значение типа {type(value).__name__} в JSON'
            )
    
    def _deserialize(self, data: bytes) -> Optional[Any]:
        """Десериализация значений из Redis"""
        if not data:
            return None
        
        try:
            return json.loads(data.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            logger.error(
                'redis_cache_deserialization_failed',
                data_sample=str(data[:100]),
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True
            )
            return None
    
    def get(self, key: str) -> Optional[Any]:
        """
        Получение значения из кэша

        Args:
            key (str): Key

        Returns:
            Optional[Any]: Value or None
        """
        self.stats['total_operations'] += 1

        if not self._ensure_connection():
            self.stats['misses'] += 1
            return None
        
        try:
            cache_key = self._build_key(key)
            data = self._client.get(cache_key)

            if data is not None:
                self.stats['hits'] += 1
                logger.debug('redis_cache_hit', key=key)
                return self._deserialize(data)
            else:
                self.stats['misses'] += 1
                logger.debug('redis_cache_miss', key=key)
                return None
        except RedisError as e:
            self.stats['errors'] += 1
            logger.error(
                'redis_cache_get_error',
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True
            )
            return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """
        Запись значения в кэш

        Args:
            key (str): Ключ
            value (Any): Значение
            ttl (Optional[int], optional): Время жизни значения в секундах. Defaults to None - без ограничения.

        Returns:
            bool: True - success, False - fails or error
        """
        self.stats['total_operations'] += 1
        if not self._ensure_connection():
            return False
        
        try:
            cache_key = self._build_key(key)
            serialized_value = self._serialize(value=value)
            
            if ttl:
                result = self._client.setex(cache_key, ttl, serialized_value)
            else:
                result = self._client.set(cache_key, serialized_value)
            
            if result:
                logger.debug('redis_cache_success', key=key, ttl=ttl)
                return True
            else:
                logger.warning('redis_cache_set_failed', key=key)
                return False
        except (RedisError, TypeError) as e:
            self.stats['errors'] += 1
            logger.error(
                'redis_cache_error',
                key=key,
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True
            )
            return False
    
    def delete(self, key: str) -> bool:
        """Удаление значения из Redis кэша"""
        self.stats['total_operations'] += 1
        
        if not self._ensure_connection():
            return False
        
        try:
            cache_key = self._build_key(key)
            result = self._client.delete(cache_key)

            if result > 0:
                logger.debug('redis_cache_success', key=key)
                return True
            else:
                logger.debug('redis_cache_failed', key=key)
                return False
        except RedisError as e:
            self.stats['errors'] += 1
            logger.error(
                'redis_cache_error',
                key=key,
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True
            )
            return False
    
    def exists(self, key: str) -> bool:
        """Проверка существования ключа в кэше"""
        if not self._ensure_connection():
            return False
        
        try:
            cache_key = self._build_key(key)
            return self._client.exists(cache_key) > 0
        except RedisError as e:
            logger.error(
                'redis_cache_error',
                key=key,
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True
            )
            return False
    
    def get_many(self, keys: List[str]) -> Dict[str, Any]:
        """Получение нескольких значений за один запрос"""
        self.stats['total_operations'] += 1
        if not self._ensure_connection():
            return {}
        
        try:
            cache_keys = [self._build_key(key) for key in keys]
            values = self._client.mget(cache_keys)

            result = {}
            for key, value in zip(keys, values):
                if value is not None:
                    result[key] = self._deserialize(value)
                    self.stats['hits'] += 1
                else:
                    self.stats['misses'] += 1
            
            logger.debug(
                'redis_cache_get_many',
                keys_count=len(keys),
                found_count=len(result)
            )
            return result
        except RedisError as e:
            self.stats['errors'] += 1
            logger.error(
                'redis_cache_get_many_error',
                keys_count=len(keys),
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True
            )
            return {}
    
    def set_many(self, data: Dict[str, Any], ttl: Optional[int] = None) -> bool:
        """Установка нескольких значений за один запрос"""
        self.stats['total_operations'] += 1
        
        if not self._ensure_connection():
            return False
        
        try:
            pipline = self._client.pipeline()

            for key, value in data.items():
                cache_key = self._build_key(key)
                serialized_value = self._serialize(value)

                if ttl:
                    pipline.setex(cache_key, ttl, serialized_value)
                else:
                    pipline.set(cache_key, serialized_value)
            
            results = pipline.execute()

            is_success = all(results)
            
            logger.debug(
                'redis_cache_set_many',
                keys_count=len(data),
                succes=is_success
            )

            return is_success
        
        except (RedisError, TypeError) as e:
            self.stats['errors'] += 1
            logger.error(
                'redis_cache_set_many_error',
                keys_count=len(data),
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True
            )
            return False
    
    def clear(self) -> bool:
        """Очистка всего кэша приложения (только с префиксом)"""
    
        if not self._ensure_connection():
            return False
        
        try:
            # SCAN для итерации по ключам с префиксом
            pattern = f'{self.config.CACHE_PREFIX}*'
            keys = []

            for key in self._client.scan_iter(match=pattern):
                keys.append(key)
            
            if keys:
                self._client.delete(*keys)
                logger.info('redis_cache_cleared', keys_count=len(keys))
            else:
                logger.info('redis_cache_clear_no_keys_found')
            
            return True
        
        except RedisError as e:
            logger.error(
                'redis_cache_clear_error',
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True
            )
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики использования кэша"""
        if not self._ensure_connection():
            return self.stats
        
        try:
            # Получение дополнительной статистики из Redis
            info = self._client.info()
            cahce_stats = {
                'client_stats': self.stats,
                'redis_used_memory': info.get('used_memory_human', 'N/A'),
                'redis_connections': info.get('connected_clients', 0),
                'redis_uptime': info.get('uptime_in_seconds', 0),
                'hit_rate': (
                    self.stats['hits'] / self.stats['total_operations'] * 100
                    if self.stats['total_operations'] > 0 else 0
                )
            }
            return cahce_stats
        except RedisError:
            return self.stats
    
    def close(self):
        """Закрытие соединения с Redis"""
        if self._connection_pool:
            self._connection_pool.disconnect()
            self._is_connected = False
            self._client = None
            logger.info('redis_cache_connection_closed')



