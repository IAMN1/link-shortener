from dataclasses import dataclass

from link_shortener.application import (ExtendedLinkInfoResponse, LinkCache,
                                        Logger, ShortLinkResponse)
from link_shortener.domain import LinkNotFoundError, LinkRepository, ShortCode


@dataclass
class GetLinkInfoUseCase:
    """
    Use case: Получения информации о ссылке.
    Оркестрирует получение данных из кэша  и репозитория

    Основной сценарий при использовании:
    1. Валидирует код ссылки
    2. Поиск ссылки в кэше по коду
    3. Поиск ссылки в репозитории (если не нашли в кэше)
    4. Кэширование для будущих запросов
    5. Формирование ответа
    """

    repository: LinkRepository
    cache: LinkCache
    base_url: str
    logger: Logger

    def execute(self, short_code_str: str) -> ShortLinkResponse:
        """
        Основной сценарий использования

        Args:
            short_code_str: Короткий код ссылки

        Returns:
            ShortLinkResponse: Информация о ссылке

        Raises:
            ValueError: Если короткий код невалидный
            LinkNotFoundError: Если ссылка не найдена
        """
        try:
            # 1. Создание VO с валидацией
            short_code = ShortCode(short_code_str)

            self.logger.debug("Getting link info for", short_code=short_code.value)

            # 2. Попытка получения из кэша
            cached_link = self.cache.get_by_code(short_code)
            if cached_link:

                self.logger.info("Cache hit for code", code=short_code.value)

                return ShortLinkResponse.from_link(
                    cached_link, base_url=self.base_url, is_new=False, from_cache=True
                )

            # 3. Получение из репозитория
            link = self.repository.find_by_code(short_code)
            if not link:
                self.logger.warning("Link not found", code=short_code.value)
                raise LinkNotFoundError(short_code_str)

            # 4. Кэширование для будущих запросов
            self.cache.save(link)

            self.logger.info("Found in repository", short_code=short_code.value)

            # 5. Формирование ответа и возврат
            return ShortLinkResponse.from_link(link, self.base_url, from_cache=False)

        except ValueError as e:
            self.logger.error("Invalid short code format", short_code=short_code_str)
            raise ValueError(f"Invalid short code: {str(e)}")

        except LinkNotFoundError:
            raise

        except Exception as e:
            self.logger.exception(
                "Error getting link info", short_code=short_code_str, exc_info=str(e)
            )
            raise


@dataclass
class GetExtendLinkInfoUseCase:
    """Use case для получения расширенной информации о ссылке (с метриками)"""

    repository: LinkRepository
    cache: LinkCache
    base_url: str
    logger: Logger

    def execute(self, short_code_str: str) -> ExtendedLinkInfoResponse:
        """
        Расширенная версия с дополнительной статистикой.

        Args:
            short_code_str: Короткий код ссылки

        Returns:
            dict: Расширенная информация о ссылке
        """
        try:

            # 1. Создание VO с валидацией
            short_code = ShortCode(short_code_str)

            self.logger.debug(
                "Getting extend link info for", short_code=short_code.value
            )

            # 2. Попытка получения из кэша
            cached_link = self.cache.get_by_code(short_code)
            if cached_link:
                self.logger.info("Cache hit for code", code=short_code.value)
                return ExtendedLinkInfoResponse.from_link(
                    cached_link, base_url=self.base_url, is_new=False, from_cache=True
                )

            # 3. Получение из репозитория
            link = self.repository.find_by_code(short_code)
            if not link:
                self.logger.warning("Link not found", code=short_code.value)
                raise LinkNotFoundError(short_code_str)

            # 4. Кэширование для будущих запросов
            self.cache.save(link)

            self.logger.info("Found in repository", short_code=short_code.value)

            # Дополнительные метрики
            return ExtendedLinkInfoResponse.from_link(link, self.base_url)

        except ValueError as e:
            self.logger.error("Invalid short code format", short_code=short_code_str)
            raise ValueError(f"Invalid short code: {str(e)}")

        except LinkNotFoundError:
            raise

        except Exception as e:
            self.logger.error(
                "Error getting extended link info",
                short_code=short_code_str,
                error=str(e),
            )
            raise
