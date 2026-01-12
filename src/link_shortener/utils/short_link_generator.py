
from datetime import datetime
import hashlib
import secrets
import string

BASE_62_ALPHABET = string.ascii_lowercase + string.ascii_uppercase + string.digits
ALPHABET_LENGTH = len(BASE_62_ALPHABET)



class ShortCodeGenerator():
    """
    Класс генератор кодов по гибридной схеме
    """

    def __init__(self, id_part_length=3, random_part_length=4):
        self.id_part_length = id_part_length
        self.random_part_length = random_part_length
        self.total_length = id_part_length + random_part_length
    
    
    @staticmethod
    def _base62_encode(num: int) -> str:
        """
        Кодирование числа в base62

        Args:
            num (int): число для кодирования

        Returns:
            str: строка base62
        """
        if num == 0:
            return BASE_62_ALPHABET[0]
        
        encoded = []
        while num > 0:
            num, remainder = divmod(num, ALPHABET_LENGTH)
            encoded.append(BASE_62_ALPHABET[remainder])

        return ''.join(reversed(encoded))
    
    def _generate_fallback(self, record_id: int, existing_codes: set) -> str:
        """
        Резервный метод генерации кода

        Args:
            record_id (int): ID записи в БД
            existing_codes (set): Множество существующих кодов
              для проверки коллизий 

        Raises:
            ValueError: Ошибка при достижении лимита попыток при создании кода

        Returns:
            str: сгенерированный код
        """

        timestamp = int(datetime.utcnow().timestamp())
        data = f"{record_id}:{timestamp}:{secrets.token_hex(4)}"
        hash_bytes = hashlib.sha256(data.encode()).digest

        hash_num = int.from_bytes(hash_bytes[:4], 'big')
        hash_part = self._base62_encode(hash_num).zfill(6)[:6]

        if hash_part not in existing_codes:
            return hash_part[:self.total_length]
        
        raise ValueError("Не удалось сгенерировать уникальный код после всех попыток!")

    
    def generate(self, record_id: int, existing_codes=None):
        """
        Основной метод генерации кода

        Args:
            record_id (int): ID записи в БД
            existing_codes (set or None): Множество существующих кодов
              для проверки коллизий. Defaults to None.

        Returns:
            _type_: _description_
        """

        if existing_codes is None:
            existing_codes = set()
        
        # первые 3 символа из base62 от ID
        id_part = self._base62_encode(record_id).zfill(self.id_part_length)[-self.id_part_length:]

        # 4 случайных символа
        # пытаемся сгенерировать за max_attempts попыток
        max_attempts = 10
        for attempt in range(max_attempts):
            random_part = ''.join(secrets.choice(BASE_62_ALPHABET) for _ in range(self.random_part_length))
        

            full_code = id_part + random_part

            if full_code not in existing_codes:
                return full_code
            
            continue

        # Если не смогли за max_attempts попыток сгенерировать,
        # тогда вызываем более надежный метод для генерации
        return self._generate_fallback(record_id, existing_codes)

    