from typing import Any, Dict, Optional

from ...entities.link import Link
from ...exceptions import LinkNotFoundError, ValidationError
from ...interfaces.database.abc_repository import ILinkRepository
from ...interfaces.logger.abc_logger import ILogger
from ...interfaces.utils.abc_code_extractor import IShortCodeExtractor
from ...value_objects.cache_strategy import InfoCacheStrategy
from ...value_objects.short_link_result import LinkInfoResult
from ..base_service import BaseService
from ..cache.cache_manager import CacheManager


class LinkInformation(BaseService):
    """
    Сервис для получения полной информации о ссылке
    """

    def __init__(
        self,
        repository: ILinkRepository,
        short_code_extractor: IShortCodeExtractor,
        cache_manager: Optional[CacheManager] = None,
        info_strategy: Optional[InfoCacheStrategy] = None,
        cache_ttl: int = 300,
        logger: Optional[ILogger] = None,
    ):
        super().__init__(logger)
        self._code_extractor = short_code_extractor
        self._repository = repository
        self._cache_manager = cache_manager
        self._info_strategy = info_strategy
        self._cache_ttl = cache_ttl

    def extract_short_code(self, short_url: str) -> str:
        """
        Извлекает короткий код из короткой ссылки

        Args:
            short_url: Полная короткая ссылка

        Returns:
            str: Короткий код

        Raises:
            ValidationError: Если ссылка имеет неверный формат
        """
        is_valid, error_message = self._code_extractor.validate_short_url_format(
            short_url
        )
        if not is_valid:
            raise ValidationError(
                message=error_message,
                code="INVALID_SHORT_URL_FORMAT",
                field="short_url",
                value=short_url,
            )

        short_code = self._code_extractor.extract_code_from_url(short_url)
        if not short_code:
            raise ValidationError(
                message="Не удалось извлечь короткий код из ссылки",
                code="SHORT_CODE_EXTRACTION_FAILED",
                field="short_url",
                value=short_url,
            )

        return short_code

    def get_link_info(self, short_url: str) -> LinkInfoResult:
        """
        Получает полную информацию о ссылке

        Args:
            short_url (str): Cокращенная ссылка

        Returns:
            LinkInfoResult: Полная информация о ссылке

        Raises:
            NotFoundError: если ссылка не найдена
            LinkNotFoundError: если ссылка не найдена
        """
        self._log_debug("получение информации о ссылке", short_url=short_url)

        short_code = self.extract_short_code(short_url)

        # 1. Получение из кэша
        cached_link = None
        if self._cache_manager and self._info_strategy:
            cached_link = self._cache_manager.get_link_info(
                short_code, self._info_strategy
            )

            if cached_link:
                self._log_debug("информация найдена в кэше", short_code=short_code)
                try:
                    return self._link_to_info_result(cached_link)
                except Exception as e:
                    self._log_error(
                        "Ошибка десериализации из кэша",
                        short_code=short_code,
                        error=str(e),
                    )

        # 2. Получение из бд
        link = self._repository.get_by_short_code(short_code)
        if not link:
            raise LinkNotFoundError(f"Ссылка с кодом ({short_code}) не найдена!")

        # 3. Формирование результата
        result = self._link_to_info_result(link)

        # 4. Кэширование данных
        if self._cache_manager and self._info_strategy:
            success = self._cache_manager.cache_link(
                link, {"info": self._info_strategy}, self._cache_ttl
            )

            if success:
                self._log_debug(
                    "Информация о ссылке закэширована", short_code=short_code
                )
        return result

    def _link_to_info_result(self, link: Link) -> LinkInfoResult:
        """Конвертация Link сущности в LinkInfoResult"""
        return LinkInfoResult(
            id=link.id,
            url_hash=link.url_hash,
            short_code=link.short_code,
            original_url=link.original_url,
            clicks=link.clicks,
            created_at=link.created_at.isoformat(),
            last_accessed=(
                link.last_accessed.isoformat() if link.last_accessed else None
            ),
        )

    def get_link_info_with_cache(
        self, short_code: str, base_url: str
    ) -> Dict[str, Any]:
        """
        Получение информации о ссылке с добавлением short_url
        Используется на уровне приложения

        Args:
            short_code (str): короткий код ссылки
            base_url (str): Базовый Url для формирования short_url

        Returns:
            Dict[str, Any]: Информация о ссылке в формате API
        """
        result = self.get_link_info(short_code)

        return {
            "short_code": result.short_code,
            "short_url": f"{base_url.rstrip('/')}/{result.short_code}",
            "original_url": result.original_url,
            "clicks": result.clicks,
            "created_at": result.created_at,
            "last_accessed": result.last_accessed,
        }
