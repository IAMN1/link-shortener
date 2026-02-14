from dataclasses import dataclass

from link_shortener.application import LinkCache, Logger, ShortLinkResponse
from link_shortener.domain import (Link, LinkRepository, OriginalUrl,
                                   ShortCode, ShorteningPolicy)


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
    logger: Logger
    max_collision_attempts: int = 5

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
            # Создание VO c валидацией
            original_url = OriginalUrl(url)

            self.logger.info(
                "Starting short link creation", url=original_url.value[:50]
            )

            # Вычисление хэша для дедупликации
            url_hash = self.shortening_policy.calculate_hash(original_url)

            # 1. Проверка кэша
            cached_link = self.cache.get_by_hash(url_hash)
            if cached_link:
                self.logger.debug(
                    "Cache hit for Url,", url=url[:50], hash=url_hash.value[:10]
                )
                return ShortLinkResponse.from_link(
                    cached_link, base_url=self.base_url, from_cache=True
                )

            # 2. Проверка репозитория
            existing_link = self.repository.find_by_hash(url_hash)
            if existing_link:
                self.logger.debug("Found in repository", hash=url_hash.value[:10])
                # Кэширование
                self.cache.save(existing_link)
                return ShortLinkResponse.from_link(
                    link=existing_link,
                    base_url=self.base_url,
                    is_new=False,
                    from_cache=False,
                )

            # 3. Генерация кода
            short_code = self._generate_unique_code(original_url)

            # Создание доменной сущности
            new_link = Link.create(
                url_hash=url_hash, short_code=short_code, original_url=original_url
            )

            # 4. Сохранение в репозиторий и кэш
            saved_link = self.repository.save(new_link)
            self.cache.save(saved_link)

            self.logger.info(
                "Short link created successfully", short_code=short_code.value
            )

            return ShortLinkResponse.from_link(
                link=saved_link, base_url=self.base_url, is_new=True
            )
        except ValueError as e:
            self.logger.error("Validation failed", url=url[:50], error=str(e))
            raise ValueError(f"Invalid URL {str(e)}")

        except Exception as e:
            self.logger.error("Error creating short link", error=str(e))
            raise

    def _generate_unique_code(self, original_url: OriginalUrl) -> ShortCode:
        """Генерация уникального кода с проверкой коллизии в репозитории"""
        attempt = 0
        while attempt < self.max_collision_attempts:

            code = self.shortening_policy.generate_unique_code(original_url, attempt)

            existing = self.repository.find_by_code(code)
            if (
                not existing
                or existing.url_hash
                == self.shortening_policy.calculate_hash(original_url)
            ):
                # коллизии нет или это та же самая ссылка (не должно произойти, но на всякий случай)
                return code

            # Колизия
            attempt += 1
        raise RuntimeError(
            "Failed to generate unique short code after multiple attempts"
        )
