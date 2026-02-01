from http import HTTPStatus


# ========== APPLICATION ERRORS ==========
class AppException(Exception):
    """Базовый класс исключений приложения"""
    def __init__(self, message: str, code: str = None, status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR):
        super().__init__(message)
        self.message = message
        self.code=code
        self.status_code = status_code
    
    def __str__(self):
        return f'{self.__class__.__name__}: {self.message} \
            (code: {self.code}, status: {self.status_code})'

class ValidationError(AppException):
    """Validation Error"""
    def __init__(self, message: str, code: str = "VALIDATION_ERROR"):
        super().__init__(message, code, HTTPStatus.BAD_REQUEST)

class NotFoundError(AppException):
    """Ресурс не найден"""
    def __init__(self, message: str, code: str = "NOT_FOUND_ERROR"):
        super().__init__(message, code, HTTPStatus.NOT_FOUND)

class RateLimitError(AppException):
    """Превышен лимит запросов"""
    def __init__(self, message: str, code: str = "RATE_LIMIT_EXEEDED"):
        super().__init__(message, code, HTTPStatus.TOO_MANY_REQUESTS)

class AuthenticationError(AppException):
    """Ошибка аутентификации"""
    def __init__(self, message: str, code: str = "AUTHENTICATION_ERROR" ):
        super().__init__(message, code, HTTPStatus.UNAUTHORIZED)

class AuthorizationError(AppException):
    """Ошибка авторизации"""
    def __init__(self, message: str, code: str = "AUTHORIZATION_ERROR" ):
        super().__init__(message, code, HTTPStatus.FORBIDDEN)


# ========== CONFIGURATION ERRORS ==========
class ConfigurationError(AppException):
    """Ошибка конфигурации"""
    def __init__(self, message: str, code: str = "CONFIGURATION_ERROR"):
        super().__init__(message, code, HTTPStatus.INTERNAL_SERVER_ERROR)

# ========== DATABASE ERRORS ==========
class DatabaseError(AppException):
    """Ошибка базы данных"""
    def __init__(self, message: str, code: str = "DATABASE_ERROR"):
        super().__init__(message, code, HTTPStatus.INTERNAL_SERVER_ERROR)

class DatabaseConnectionError(DatabaseError):
    """Ошибка подключения к Базе Данных"""
    def __init__(self, message: str, code: str = "DATABASE_CONNECTION_ERROR"):
        super().__init__(message, code)
        self.status_code = HTTPStatus.SERVICE_UNAVAILABLE

class DatabaseIntegrityError(DatabaseError):
    """Ошибка целостности базы данных"""
    def __init__(self, message: str, code: str = "DATABASE_INTEGRITY_ERROR"):
        super().__init__(message, code)
        self.status_code = HTTPStatus.CONFLICT

# ========== CACHE ERRORS ==========
class CacheError(AppException):
    """Ошибка кэша"""
    def __init__(self, message: str, code: str = "CACHE_ERROR"):
        super().__init__(message, code, HTTPStatus.INTERNAL_SERVER_ERROR)

# ========== SERVICE ERRORS ==========
class ServiceError(AppException):
    """Ошибка сервиса"""
    def __init__(self, message: str, code: str = "SERVICE_ERROR"):
        super().__init__(message, code, HTTPStatus.INTERNAL_SERVER_ERROR)

class ExternalServiceError(AppException):
    """Ошибка внешнего сервиса"""
    def __init__(self, message: str, code: str = "EXTERNAL_SERVICE_ERROR"):
        super().__init__(message, code, HTTPStatus.BAD_GATEWAY)