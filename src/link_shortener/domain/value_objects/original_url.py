from dataclasses import dataclass
import ipaddress
from urllib.parse import ParseResult, urlparse
import re

@dataclass(frozen=True)
class OriginalUrl:
    """
    Value object для оригинального URL.
    Содержит бизнес правила валидации.
    """

    value: str

    def __post_init__(self):
        self._validate_length()
        parsed = urlparse(self.value)
        self._validate_scheme(parsed)
        self._validate_netloc(parsed)
        self._validate_path(parsed)

    # ------------------------------------------------------------------
    # Методы валидации
    # ------------------------------------------------------------------

    def _validate_length(self) -> None:
        if len(self.value) > 2048:
            raise ValueError("URL too long (max 2048 characters)")

    def _validate_scheme(self, parsed) -> None:
        parsed = urlparse(self.value)
        if not parsed.scheme:
            raise ValueError("URL must have a scheme (http:// or https://)")

        if parsed.scheme not in ["http", "https"]:
            raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")

    def _validate_netloc(self, parsed) -> None:
        if not parsed.netloc:
            raise ValueError("URL must have a domain!")
        
        hostname = parsed.hostname
        if not hostname:
            raise ValueError("URL must have a hostname")
        
        try:
            if parsed.port is not None and not (1 <= parsed.port <= 65535):
                raise ValueError("Invalid port number")
        except ValueError as e:
            raise ValueError("Invalid port number") from e

        # # Разбор хоста и порта
        # host = parsed.netloc
        # if ':' in host:
        #     host, port_str = host.rsplit(":", 1)
        #     if not port_str.isdigit() or not (1 <= int(port_str) <= 65535):
        #         raise ValueError("Invalid port number")
        
        self._validate_host(hostname)
    
    def _validate_host(self, host: str) -> None:
        """проверка корректности хоста (IP or domain name)"""

        # Если ip
        try:
            ipaddress.ip_address(host)
            return # IP is correct
        except ValueError:
            pass
        
        # Если localhost
        if host == "localhost":
            return

        # Для обычных доменных имен требуем хотя бы одну точку
        if '.' not in host:
            raise ValueError("Host must contain a dot (e.g., example.com)")

        # Иначе проврка как доменного имени
        if not host:
            raise ValueError("Empty host")
        
        # Общаяя длинна не более 253
        if len(host) > 253:
            raise ValueError("Host too long")
        
        # Каждая метка
        labels = host.split(".")
        for label in labels:
            
            if not label:
                raise ValueError ("Empty label in host")
            if len(host) > 63:
                raise ValueError("Label too long")
            
            # Допустимые символы:
            # буквы, цифры, дефис, но не начинается и не заканчивается дефисом
            if not re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$', label):
                raise ValueError(f"Invalid characters in host label: {label}")
    
    def _validate_path(self, parsed) -> None:
        if parsed.path and any(ord(c) < 32 or ord(c) == 127 for c in parsed.path):
            raise ValueError("Path contains control characters")

    # ------------------------------------------------------------------
    # Публичные методы
    # ------------------------------------------------------------------

    def __str__(self) -> str:
        return self.value

    def get_domain(self) -> str:
        """Бизнес метод: извлечение домена с портом"""
        parsed = urlparse(self.value)
        return parsed.hostname or ""

    def normalize(self) -> str:
        """Бизнес метод: нормализации URL"""

        parsed = urlparse(self.value)
        path = parsed.path if parsed.path else "/"

        normalized = ParseResult(
            scheme=parsed.scheme.lower(),
            netloc=parsed.netloc.lower(),
            path=path,
            params=parsed.params,
            query=parsed.query,
            fragment="",
        ).geturl()
        return normalized
