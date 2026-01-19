from http import HTTPStatus

class AppException(Exception):
    """Базовый класс исключений приложения"""
    def __init__(self, message: str, code: str = None, status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.code=code
        self.status_code = status_code
    
    # def to_dict(self):
    #     return {
    #         'error': self.message,
    #         'code': self.code,
    #         'status_code': self.status_code
    #     }


class ValidationError(AppException):
    """Validation Error"""
    def __init__(self, message: str, code: str = None):
        super().__init__(message, code, HTTPStatus.BAD_REQUEST)


class NotFoundError(AppException):
    """Ресурс не найден"""
    def __init__(self, message: str, code: str = None):
        super().__init__(message, code, HTTPStatus.NOT_FOUND)

class RateLimitError(AppException):
    """Превышен лимит запросов"""
    def __init__(self, message: str, code: str = None):
        super().__init__(message, code, HTTPStatus.TOO_MANY_REQUESTS)

class DataBaseError(AppException):
    """Ошибка базы данных"""
    def __init__(self, message: str, code: str = None):
        super().__init__(message, code, HTTPStatus.INTERNAL_SERVER_ERROR)

class ServiceError(AppException):
    """Ошибка сервиса"""
    def __init__(self, message: str, code: str = None):
        super().__init__(message, code, HTTPStatus.INTERNAL_SERVER_ERROR)