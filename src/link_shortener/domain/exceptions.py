class DomainError(Exception):
    """Базовые исключения доменного слоя"""
    def __init__(self, message: str, code: str = "DOMAIN_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class ValidationError(DomainError):
    """Ошибка валидации"""

    def __init__(self, message: str, field: str = None):
        super().__init__(message, code="VALIDATION_ERROR")
        self.field = field


class LinkNotFoundError(DomainError):
    """Ссылка не найдена"""

    def __init__(self, short_code: str = None):
        message = 'Link not found'
        if short_code:
            message = f'Link with code ({short_code}) not found'
        super().__init__(message, "LINK_NOT_FOUND")