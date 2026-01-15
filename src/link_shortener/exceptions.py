class AppException(Exception):
    """Базовый класс исключений приложения"""
    def __init__(self, message: str, code: str = None):
        super().__init__(message)
        self.message = message
        self.code=code


class ValidationError(AppException):
    """Validation Error"""
    pass

class NotFoundError(AppException):
    """Ресурс не найден"""
    pass

class RateLimitError(AppException):
    """Превышен лимит запросов"""
    pass

class DataBaseError(AppException):
    """Ошибка базы данных"""
    pass