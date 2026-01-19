from typing import Dict, List
from link_shortener.core.config import BaseConfig
from link_shortener.database.crud import URLCrud
from link_shortener.database.models import TableURL
from link_shortener.core.exceptions import NotFoundError, ServiceError, ValidationError
from link_shortener.utils.short_code_generator import HashBasedGenerator
from link_shortener.utils.url_validators import UrlValidator


# TODO Add logging

class LinkService:
    def __init__(self, code_generator=None, base_url=None, cache_client=None):
        self.generator = code_generator or HashBasedGenerator(
            code_length=BaseConfig.SHORT_CODE_LENGTH, 
            pepper=BaseConfig.SHORT_CODE_SECRET_PEPPER
        )
        self.base_url = base_url or BaseConfig.BASE_LINK
        self.cache = cache_client

    
    def create_short_url(self, original_url: str) -> Dict:
        """
        Создание короткой URL

        Args:
            original_url (str): Оригинальная URL

        Returns:
            dict: Словарь с результатом
        """
        
        # Валидация и нормализация url
        is_valid, result = UrlValidator.is_valid_url(original_url)
        if not is_valid:
            raise ValidationError(result, 'INVALID_URL')
        
        normalized_url = result

        # TODO добавить проверку кэша
        # Проверка кэша (уменьшает нагрузку на БД)

        # Генерация хэша для дедупликации и кода
        url_hash = self.generator.calculate_deduplication_hash(normalized_url)
        short_code = self.generator.generate_code(normalized_url)

        # Сохранение в бд
        try:
            short_url, is_created = URLCrud.create_or_get(
                source_url=original_url,
                url_hash=url_hash,
                short_code=short_code
            )
            
            # Формирование ответа
            response = self._format_response(short_url, is_created)

            # TODO Добавить кэширование созданного элемента
            
            # TODO Добавить логирование

            return response
        
        except ValidationError:
            raise # top level
        except Exception as e:
            # TODO логирование ошибки
            raise ServiceError(
                "Внутренняя ошибка при создании ссылки",
                "SERVICE_ERROR"   
            )
    
    def get_original_url(self, short_code: str) -> Dict:
        """
        Получение оригинального URL

        Args:
            short_code (str): Короткий код

        Returns:
            Dict: словарь с данными URL
        """
        try:

            # Проверка кэша
            # TODO Добавить проверку наличия в кэше

            # Поиск и извлечение из БД
            short_url = URLCrud.get_by_short_code(short_code)

            if not short_url:
                raise NotFoundError(
                    f'Короткая ссылка c {short_code} не найдена', 
                    'URL_NOT_FOUND'
                )
            
            return {
                'url_hash': short_url.url_hash,
                'original_url': short_url.original_url,
                'short_url': f'{self.base_url}{short_code}',
                'short_code': short_code,
                'clicks': short_url.clicks,
                'created_at': short_url.created_at.isoformat(),
                'last_accessed': short_url.last_accessed.isoformat() if short_url.last_accessed else None,
            }
        except (NotFoundError):
            raise # top level
        except Exception as e:
            # TODO add logger
            raise ServiceError(
                'Внутрення ошибка при получении ссылки',
                'SERVICE_ERROR'
            )
    
    def batch_create(self, urls: List[str]) -> List[Dict]:
        """
        Пакетное создание ссылок

        Args:
            urls (List[str]): Список URL

        Returns:
            List[Dict]: Список созданных URL
        """
        # Массив с созданными ссылками и ошибочными при нормализации
        results = []
        # Массим с успешно нормализованными ссылками
        url_data_for_bulk = []

        # 1. Обработка ссылок
        for url in urls:
            try:
                # Валидация
                is_valid, url_or_message = UrlValidator.is_valid_url(url)
                if not is_valid:
                    results.append({
                        'success': False,
                        'url': url,
                        'error': url_or_message,
                        'code': 'INVALID_URL'})
                    continue

                # Генерация хэшей и кодов для ссылок
                url_hash = self.generator.calculate_deduplication_hash(url_or_message)
                short_code = self.generator.generate_code(url_or_message)

                url_data_for_bulk.append({
                    'url_hash': url_hash,
                    'original_url': url_or_message,
                    'short_code': short_code
                })
            
            except Exception as e:
                # TODO add logger
                # TODO заменить str(e) на message, а сам str(e) записывать в log
                results.append({'success': False, 'url': url, 'error': str(e)})
            
        # 2. Пакетное сохранение в БД
        if url_data_for_bulk:
            try:
                created_urls = URLCrud.bulk_create(url_data_for_bulk)

                for url in created_urls:
                    results.append(self._format_response(url, True))

            except Exception as e:
                # TODO add logger
                for data in url_data_for_bulk:
                    results.append({
                        'success': False,
                        'url': data['original_url'],
                        'error': 'Ошибка при сохранении в БД',
                        'code': 'DB_SAVE_ERROR'
                    })
        
        return results
    
    def get_service_stats(self, stats: Dict) -> Dict:
        """
        Получение статистики сервиса

        Returns:
            Dict: Стастистика
        """
        stats = URLCrud.get_stats()
        
        total_urls = stats.get('total_urls', 0)
        total_clicks = stats.get('total_clicks', 0)
        avg_clicks = round((total_clicks /  total_urls if total_clicks else 0), 2)
        popular_urls = stats.get('popular_urls', [])

        return {
            'total_urls': total_urls,
            'total_clicks': total_clicks,
            'avg_clicks_per_url': avg_clicks,
            'popular_urls': [{
                'short_code': url.short_code,
                'short_url': f'{self.base_url}{url.short_code}',
                'clicks': url.clicks,
                'original_url': (url.original_url[:50] + '...' 
                                 if len(url.original_url) > 50 
                                 else url.original_url)
            } for url in popular_urls]
        }
    
    def cleanup_cache(self):
        """
        Очистка кэша
        """
        # TODO Добавить отчистку кэша
        pass
    
    def _format_response(self, element: TableURL, created: bool) -> Dict:
        """Форматирование итогового ответа"""

        result = {
            'already_exists': not created,
            'short_code': element.short_code,
            'short_url': f'{self.base_url}{element.short_code}',
            'original_url': element.original_url,
            'clicks': element.clicks,
            'created_at': element.created_at.isoformat(),
            'message': 'Ссылка уже существует' if not created else 'Ссылка успешно создана'
        }

        if element.last_accessed:
            result['last_accessed'] = element.last_accessed.isoformat()
        
        return result

# instance
link_service = LinkService()
