import re
from urllib.parse import urlparse, urlunparse
import validators
from src.link_shortener.core.config import Config

class UrlValidator:
    """
    Класс валидатор для проверки безопасности
    """

    DANGEROUS_SHEMES = ['javascript', 'data', 'file', 'vbscript']
    IP_PATTERN = re.compile(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$')
    OWN_DOMAINS = ['localhost', '127.0.0.1']

    @classmethod
    def is_valid_url(cls, url: str) -> tuple[bool, str]:
        """
        Проверка URL на валидность и безопасность

        Args:
            url (str): ссылка для проверки

        Returns:
            tuple[bool, str]: кортеж со статусом проверки и сообщением в случае
              не удачи или нормализованной ссылкой в случае успеха
        """
        
        # проверка длинны ссылки
        if len(url) > Config.MAX_URL_LENGTH:
            return False, f'URL длинна превышаем максимальное количество символов {Config.MAX_URL_LENGTH}'


        if not validators.url(url):
            return False, 'Некорректный URL'
        
        # URL parse
        try:
            parsed = urlparse(url)
        except Exception:
            return False, "Не удалось разобрать URL"
        
        # Проверка схемы
        if not parsed.scheme:
            return False, 'URL должен содержать схему(http:// или https://)'
        
        if parsed.scheme.lower() in cls.DANGEROUS_SHEMES:
            return False, f'Опасная схема URL: {parsed.scheme}'
        
        if parsed.scheme.lower() not in Config.ALLOWED_SHEMES:
            return False, f'Недопустимая схема! Разрешены: {''.join(Config.ALLOWED_SHEMES)}'
        
        
        # проверка домена
        if not parsed.netloc:
            return False, 'URL должен содержать домен!'
        
        # Проверка на IP
        if cls.IP_PATTERN.match(parsed.netloc.split(':')[0]):
            return False, 'URL с IP-адресом вместо домена не разрешены!'
        
        # проверка ссылок с наши домены (предотвращение циклов)
        if any(domain in parsed.netloc for domain in cls.OWN_DOMAINS):
            return False, 'Нельзя сокращать ссылки на этот сервис!'
        
        normalized_url = cls.normalize_url(url)
        return True, normalized_url
    
    @staticmethod
    def normalize_url(url: str) -> str:
        """
        Нормализация URL для устранения дубликатов

        Args:
            url (str): ссылка

        Returns:
            str: нормализованная ссылка
        """
        
        parsed = urlparse(url)

        # Убираем фрагмент (#achor) т.к он клиентский
        parsed = parsed._replace(fragment='')

        # Приводим хост к нижнему регистру
        parsed = parsed._replace(sheme=parsed.scheme.lower())

        if parsed.netloc:
            parsed = parsed._replace(netloc=parsed.netloc.lower())
        
        # Убираем стандартные порты
        if parsed.scheme == 'http' and parsed.port == 80:
            parsed = parsed._replace(netloc=parsed.hostname)
        elif parsed.scheme == 'https' and parsed.port == 443:
            parsed = parsed._replace(netloc=parsed.hostname)
        
        return urlunparse(parsed)
    
    @classmethod
    def extract_domain(cls, url: str) -> str:
        """
        Извлечение домена

        Args:
            url (str): ссылка

        Returns:
            str: домен
        """
        parsed = urlparse(url)
        return parsed.netloc

