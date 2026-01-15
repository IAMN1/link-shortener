from typing import Dict, List
from link_shortener.core.config import BaseConfig
from link_shortener.database.crud import URLCrud
from link_shortener.database.models import TableURL
from link_shortener.exceptions import NotFoundError, ValidationError
from link_shortener.utils.short_link_generator import HashBasedGenerator
from link_shortener.utils.url_validators import UrlValidator


class LinkService:
    def __init__(self):
        self.generator = HashBasedGenerator(
            code_length=BaseConfig.SHORT_CODE_LENGTH,
            pepper=BaseConfig.SHORT_CODE_SECRET_PEPPER
        )
        self.base_url = BaseConfig.BASE_LINK
        # TODO добавить кэш redis

    
    def create_short_url(self, original_url: str) -> dict:
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
                normalized_url=original_url,
                url_hash=url_hash,
                short_code=short_code
            )
            
            # Формирование ответа
            response = self._format_response(short_url, is_created)

            # TODO Добавить кэширование созданного элемента
            
            # TODO Добавить логирование

            return response
        except Exception as e:
            # TODO логирование ошибки
            raise ValidationError(
                "Внутренняя ошибка при создании ссылки",
                "INTERNAL_ERROR"   
            )
    
    def get_original_url(self, short_code: str) -> str:
        """
        Получение оригинального URL

        Args:
            short_code (str): Короткий код

        Returns:
            str: Оригинальный URL
        """
        # Проверка кэша
        # TODO Добавить проверку наличия в кэше

        # Поиск и извлечение из БД
        short_url = URLCrud.get_by_short_code(short_code)

        if not short_url:
            raise NotFoundError('Короткая ссылка не найдена', 'URL_NOT_FOUND')
        
        return {
            'url_hash': short_url.url_hash,
            'Original_url': short_url.original_url,
            'short_url': f'{self.base_url}{short_code}',
            'short_code': short_code,
            'clicks': short_url.clicks,
            'created_at': short_url.created_at.isoformat(),
            'last_accessed': short_url.last_accessed.isoformat() if short_url.last_accessed else None,
        }
    
    def bathc_create(self, urls: List[str]) -> List[Dict]:
        """
        Пакетное создание ссылок

        Args:
            urls (List[str]): Список URL

        Returns:
            List[Dict]: Список созданный URL
        """
        # Массив с созданными ссылками и ошибочными при нормализации
        results = []
        # Массим с успешно нормализованными ссылками
        url_data_for_bulk = []

        for url in urls:
            try:
                is_valid, result = UrlValidator.is_valid_url(url)
                if not is_valid:
                    results.append({'url': url, 'error': result})
                    continue

                # Генерация хэшей и кодов для ссылок
                url_hash = self.generator.calculate_deduplication_hash(result)
                short_code = self.generator.generate_code(result)

                url_data_for_bulk.append({
                    'original_url': result,
                    'url_hash': url_hash,
                    'short_code': short_code
                })
            
            except Exception as e:
                results.append({'url': url, 'error': str(e)})
            
        # Пакетное сохранение в БД
        if url_data_for_bulk:
            created_urls = URLCrud.bulk_create(url_data_for_bulk)

            for url in created_urls:
                results.append(self._format_response(url, True))
        
        return results
    
    def get_service_stats(self) -> Dict:
        """
        Получение статистики сервиса

        Returns:
            Dict: Стастистика
        """
        return URLCrud.get_stats()
    

    def cleanup_cache(self):
        """
        Очистка кэша
        """
        # TODO Добавить отчистку кэша
        pass
    

    def _format_response(self, element: TableURL, created: bool) -> Dict:
        """Форматирование итогового ответа"""
        return {
            'already_exists': not created,
            'short_code': element.short_code,
            'short_url': f'{self.base_url}{element.short_code}',
            'original_url': element.original_url,
            'clicks': element.clicks,
            'created_at': element.created_at.isoformat(),
            'message': 'Ссылка уже существует' if not created else 'Ссылка успешно создана'
        }

# instance
link_service = LinkService()
