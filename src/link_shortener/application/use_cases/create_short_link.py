from dataclasses import dataclass
from typing import Optional

from src.link_shortener.application.dtos.responses import ShortLinkResponse
from src.link_shortener.application.ports.cache.link_cache import LinkCache
from src.link_shortener.application.ports.logger.logger import Logger
from src.link_shortener.domain.entities.link import Link
from src.link_shortener.domain.policies.shortening_policy import ShorteningPolicy
from src.link_shortener.domain.repositories.link_repository import LinkRepository
from src.link_shortener.domain.value_objects.original_url import OriginalUrl


@dataclass
class CreateShortLinkUseCase:
    """
    Use case: Создания короткой ссылки.
    Оркестрирует доменные объекты и внешние системы

    Основной сценарий при использовании:
    1. Валидирует и нормализует через VO
    2. Проверяет на дедупликацию (в БД и кэше)
    3. Генерирует код для ссылки
    4. Сохраняет ссылку
    """

    repository: LinkRepository
    cache: LinkCache
    shortening_policy: ShorteningPolicy
    base_url: str
    logger: Optional[Logger] = None

    def execute(self, url: str) -> ShortLinkResponse:
        """
        Основной сценарий использования

        Args:
            url (str): Ссылка для сокращения
            
        Returns:
            ShortLinkResponse: Информация о ссылке
        
        Riases:
            ValueError: Если URL невалидный
        """
        try:
            # 1. создание VO c валидацией
            original_url = OriginalUrl(url)

            if self.logger:
                self.logger.info('Starting short link creation', url=original_url.value[:50])

            # 2. вычисление хэша для дедупликации
            url_hash = self.shortening_policy.calculate_hash(original_url)

            # 3. Проверка кэша
            cached_link = self.cache.get_by_hash(url_hash)
            if cached_link:
                if self.logger:
                    self.logger.debug('Cache hit for Url,', url=url[:50], hash=url_hash.value[:10])
                return ShortLinkResponse.from_link(cached_link, from_cache=True)
            
            # 4. Проверка репозитория
            existing_link = self.repository.find_by_hash(url_hash)
            if existing_link:
                if self.logger:
                    self.logger.debug('Found in repository', hash=url_hash.value[:10])
                # Кэширование
                self.cache.save(existing_link)
                return ShortLinkResponse.from_link(cached_link, from_cache=True)
            
            # 5. Генерация кода
            short_code = self.shortening_policy.generate_code(original_url)

            # 6 Создание доменной сущности
            new_link = Link.create(
                url_hash=url_hash,
                short_code=short_code,
                original_url=original_url
            )

            # 7. Сохранение в репозиторий и кэщ
            saved_link = self.repository.save(new_link)
            self.cache.save(saved_link)

            if self.logger:
                self.logger.info(
                    'Short link created successfully',
                    short_code=short_code
                )
            
            return ShortLinkResponse.from_link(
                saved_link,
                base_url=self.base_url,
                is_new=True
            )
        except ValueError as e:
            if self.logger:
                self.logger.error('Validation failed', url=url[:50], error=str(e))
            raise ValueError(f'Invalid URL {str(e)}')
        except Exception as e:
            if self.logger:
                self.logger.error('Error creating short link', error=str(e))
            raise
