
import hashlib
import secrets
import string
from typing import Optional

BASE_62_ALPHABET = string.ascii_lowercase + string.ascii_uppercase + string.digits
ALPHABET_LENGTH = len(BASE_62_ALPHABET)



class HashBasedGenerator():
    """
    Генератор на основе хеширования URL
    - Один Url = один код
    - Криптографически безопасный
    - Поддерживает дедупликацию
    """

    def __init__(self, code_length=7, pepper: Optional[str]=None):
        """
        Конструктов класса с инициализацией полей
        Args:
            code_length (int, optional): Длинна короткого кода. Defaults to 7.
            TODO Позже добавить возможность менять длинну (6-8 символов)
            pepper (Optional[str], optional): Секретный ключь для усиления безопасности. Defaults to None.
        """
        self.code_length = code_length
        self.pepper = pepper or secrets.token_hex(32)
    

    def generate(self, normalized_original_url: str) -> str:
        """
        Генерация кода на основе хеша URL

        Args:
            normalized_original_url (str): нормализированный оригинальный URL

        Returns:
            str: короткий код фиксированной длинны
        """

        # 1. вычисление хэша с перцем
        url_hash = self._calculate_hash(normalized_original_url)

        # 2. конвертация в base62
        result = self._hash_to_base62(url_hash)
        return result
    

    def _calculate_hash(self, normalized_original_url) -> bytes:
        """
        Вычисление хэша URL с использованием перца

        Args:
            normalized_original_url (_type_): нормализированный оригинальный URL

        Returns:
            bytes: Хэш оригинального URL
        """
        data = f'{normalized_original_url}:{self.pepper}'.encode('utf-8')
        return hashlib.blake2b(data, digest_size=32).digest()
    
    def _hash_to_base62(self, hash_url: bytes) -> str:
        """
        Конвертация хэша в base62 строку

        Args:
            hash_url (bytes): Хэш URL

        Returns:
            str: короткий код ссылки
        """
        
        # Берет первые N байт для нужной длинны
        bytes_needed = (self.code_length * 6 + 7) // 8 # окрегдение вверх
        truncated_hash = hash_url[:bytes_needed]

        # конвертация в число
        num = int.from_bytes(truncated_hash, 'big')

        # Кодирование в base62
        if num == 0:
            return BASE_62_ALPHABET[0] * self.code_length

        encoded = []
        for i in range(self.code_length):
            if num > 0:
                num, remainder = divmod(num, ALPHABET_LENGTH)
                encoded.append(BASE_62_ALPHABET[remainder])
            else:
                encoded.append(BASE_62_ALPHABET[0])
        
        return ''.join(reversed(encoded))

    
    @staticmethod
    def calculate_entropy(code_length: int) -> tuple:
        """
        Расчет энтропии для оценки безопасности

        Args:
            code_length (int): длина короткого кода

        Returns:
            tuple: энтропия в битах, количство вариантов 
        """
        import math
        bits = math.log2(62 ** code_length)
        variants = code_length * (62 ** code_length)
        return bits, variants
    
    # Пример расчета:
    # Для 7 символов: 62^7 = 3.5 триллиона комбинаций
    # Для 8 символов: 62^8 = 218 триллионов комбинаций

    