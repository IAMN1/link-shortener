from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class OriginalUrl:
    """
    Value object для оригинального URL.
    Содержит бизнес правила валидации.
    """

    value: str

    def __post_init__(self):
        if len(self.value) > 2048:
            raise ValueError('URL too long (max 2048 characters)')
        
        parsed = urlparse(self.value)
        if not parsed.scheme:
            raise ValueError('URL must have a scheme (http:// or https://)')
        
        if parsed.scheme not in ['http', 'https']:
            raise ValueError(f'Unsupported URL scheme: {parsed.scheme}')
        
        if not parsed.netloc:
            raise ValueError('URL must have a domain!')
    
    def __str__(self) -> str:
        return self.value
    
    def get_domain(self) -> str:
        """Бизнес метод: извлечение домена"""
        return urlparse(self.value).netloc
    
    def normalize(self) -> str:
        """Бизнес метод: нормализации URL"""
        parsed = urlparse(self.value)
        normalized = parsed._replace(
            scheme=parsed.scheme.lower(),
            netloc=parsed.netloc.lower(),
            fragment=""
        )
        return normalized.geturl()
    