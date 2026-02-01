import re
from typing import Tuple
from urllib.parse import urlparse, urlunparse
import validators

from link_shortener.domain.intefaces.abc_url_validator import IUrlValidator

class UrlValidator(IUrlValidator):
    """
    Реализация валидатора URL
    - Обеспечивает проверку безопасности
    - Обеспечивает нормализацию url адресов
    """

    DANGEROUS_SHEMES = ['javascript', 'data', 'file', 'vbscript']
    IP_PATTERN = re.compile(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$')
    OWN_DOMAINS = ['localhost', '127.0.0.1']

    def __init__(self, max_url_length: int = 2048, allowed_schemes: Tuple[str, ...] = ('http', 'https')):
        self.max_url_length = max_url_length
        self.allowed_schemes = allowed_schemes

    def is_valid_url(self, url: str) -> tuple[bool, str]:
        """
        Метод проверки URL на валидность и безопасность

        Args:
            url (str): ссылка для проверки

        Returns:
            tuple[bool, str]: кортеж со статусом проверки и сообщением в случае
              не удачи или нормализованной ссылкой в случае успеха
        """
        
        # 1. Проверка длинны ссылки
        if len(url) > self.max_url_length:
            return False, f'URL длинна превышаем максимальное количество символов {self.max_url_length}'


        if not validators.url(url):
            return False, 'Некорректный URL'
        
        # 2. URL parse
        try:
            parsed = urlparse(url)
        except Exception:
            return False, "Не удалось разобрать URL"
        
        # 3. Проверка схемы
        if not parsed.scheme:
            return False, 'URL должен содержать схему(http:// или https://)'
        
        if parsed.scheme.lower() in self.DANGEROUS_SHEMES:
            return False, f'Опасная схема URL: {parsed.scheme}'
        
        if parsed.scheme.lower() not in self.allowed_schemes:
            return False, f'Недопустимая схема! Разрешены: {''.join(self.allowed_schemes)}'
        
        # 4. проверка домена
        if not parsed.netloc:
            return False, 'URL должен содержать домен!'
        
        # 5. Проверка на IP
        if self.IP_PATTERN.match(parsed.netloc.split(':')[0]):
            return False, 'URL с IP-адресом вместо домена не разрешены!'
        
        # 6. проверка ссылок с наши домены (предотвращение циклов)
        if any(domain in parsed.netloc for domain in self.OWN_DOMAINS):
            return False, 'Нельзя сокращать ссылки на этот сервис!'
        
        normalized_url = self.normalize_url(url)
        return True, normalized_url
    
    def normalize_url(self, url: str) -> str:
        """
        Метод производящий нормализацию URL для устранения дубликатов

        Args:
            url (str): ссылка

        Returns:
            str: нормализованная ссылка
        """
        
        parsed = urlparse(url)

        # Убираем фрагмент (#achor) т.к он клиентский
        parsed = parsed._replace(fragment='')

        # Приводим хост к нижнему регистру
        parsed = parsed._replace(scheme=parsed.scheme.lower())

        if parsed.netloc:
            parsed = parsed._replace(netloc=parsed.netloc.lower())
        
        # Убираем стандартные порты
        if parsed.scheme == 'http' and parsed.port == 80:
            parsed = parsed._replace(netloc=parsed.hostname)
        elif parsed.scheme == 'https' and parsed.port == 443:
            parsed = parsed._replace(netloc=parsed.hostname)
        
        return urlunparse(parsed)
    
    def extract_domain(self, url: str) -> str:
        """
        Метод извлечения домена

        Args:
            url (str): ссылка

        Returns:
            str: домен
        """
        parsed = urlparse(url)
        return parsed.netloc

