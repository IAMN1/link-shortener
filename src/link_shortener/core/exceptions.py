from http import HTTPStatus

class AppException(Exception):
    """Базовый класс исключений приложения"""
    def __init__(self, message: str, code: str = None, status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.code=code
        self.status_code = status_code
    
    def __str__(self):
        return f'{self.__class__.__name__}: {self.message} \
            (code: {self.code}, status: {self.status_code})'


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

class DatabaseError(AppException):
    """Ошибка базы данных"""
    def __init__(self, message: str, code: str = None):
        super().__init__(message, code, HTTPStatus.INTERNAL_SERVER_ERROR)

class DatabaseConnectionError(DatabaseError):
    """Ошибка подключения к Базе Данных"""
    def __init__(self, message: str, code: str = None):
        super().__init__(message, code or "DB_CONNECTION_ERROR")
        self.status_code = HTTPStatus.SERVICE_UNAVAILABLE

class DatabaseIntegrityError(DatabaseError):
    """Ошибка целостности базы данных"""
    def __init__(self, message: str, code: str = None):
        super().__init__(message, code or "DB_INTEGRITY_ERROR")
        self.status_code = HTTPStatus.CONFLICT

class ServiceError(AppException):
    """Ошибка сервиса"""
    def __init__(self, message: str, code: str = None):
        super().__init__(message, code, HTTPStatus.INTERNAL_SERVER_ERROR)

class CacheError(AppException):
    """Ошибка кэша"""
    def __init__(self, message: str, code: str = None):
        super().__init__(message, code, HTTPStatus.INTERNAL_SERVER_ERROR)

class ExternalServiceError(AppException):
    def __init__(self, message: str, code: str = None):
        super().__init__(message, code, HTTPStatus.BAD_GATEWAY)