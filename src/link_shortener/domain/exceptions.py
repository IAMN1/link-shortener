from typing import Any, Dict, Optional


class DomainError(Exception):
    """Базовые исключения доменного слоя"""
    def __init__(
        self,
        message: str,
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code or "DOMAIN_ERROR"
        self.details = details or {}


class BusinessRuleError(DomainError):
    """Нарушение бизнес правила"""

    def __init__(
        self,
        message: str,
        rule_name: Optional[str],
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message, code="BUSINESS_RULE_ERROR", details=details)
        self.rule_name = rule_name


class ValidationError(DomainError):
    """ОШибка валидации"""

    def __init__(
        self,
        message: str,
        code: Optional[str] = None,
        field: Optional[str] = None,
        value: Optional[str] = None,
    ):
        super().__init__(message, code=code or "VALIDATION_ERROR")
        self.field = field
        self.value = value


class EntityNotFoundError(DomainError):
    """Сущность не найдена"""

    def __init__(
        self,
        entity_name: str,
        entity_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):

        message = f"{entity_name} не найдена"
        if entity_id:
            message = f'{entity_name} с ID "{entity_id}" не найдена'

        super().__init__(message, code="ENTITY_NOT_FOUND", details=details)
        self.entity_name = entity_name
        self.entity_id = entity_id


class LinkNotFoundError(EntityNotFoundError):
    """Ссылка не найдена"""

    def __init__(
        self, short_code: Optional[str] = None, url_hash: Optional[str] = None
    ):

        entity_id = f'Короткий код "{short_code}"' if short_code else None
        entity_id = entity_id or (f'Хэш "{url_hash}"' if url_hash else None)
        super().__init__("Ссылка", entity_id)


class InfrastructureError(DomainError):
    """Ошибка инфраструктуры"""

    def __init__(self, message: str, service_name: Optional[str] = None):
        super().__init__(message, "INFRASTRUCTURE_ERROR")
        self.service_name = service_name
