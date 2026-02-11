from dataclasses import dataclass
import re


@dataclass(frozen=True)
class ShortCode:
    """
    Valie object для короткого кода
    Не изменяемый, содержит валидацию
    """
    value: str

    def __post_init__(self):
        """Валидация при создании объекта"""
        if not re.match(r'^[a-zA-Z0-9_-]{6,10}$', self.value):
            raise ValueError(
                f"Invalid short code format: {self.value}. "
                f"Must be 6-10 alphanumeric characters."
            )
    
    def __str__(self) -> str:
        return self.value
    
    @classmethod
    def create(cls, value: str) -> 'ShortCode':
        """Фабричный метод с явной валидацией"""
        return cls(value)