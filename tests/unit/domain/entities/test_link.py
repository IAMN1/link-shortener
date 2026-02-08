"""
Тестирование link сущности
"""

from datetime import datetime, timedelta
from unittest.mock import patch
import uuid
import pytest

from src.link_shortener.domain.entities.link import Link


@pytest.mark.unit
class TestLinkEntity:
    
    def test_create_link_with_factory_method(self):
        """тест фабричного метода создания ссылки"""
        link = Link.create(
            url_hash="hash123",
            short_code='code123',
            original_url='https://example.com'
        )

        assert isinstance(link.id, str)
        assert uuid.UUID(link.id)
        assert link.url_hash == 'hash123'
        assert link.short_code == 'code123'
        assert link.original_url == 'https://example.com'
        assert link.clicks == 0
        assert isinstance(link.created_at, datetime)
        assert link.last_accessed is None

    def test_create_link_with_custom_id(self):
        """Тест создания ссылки с кастомным ID"""
        custom_id = "custom-id-123"

        link = Link.create(
            url_hash="hash123",
            short_code='code123',
            original_url='https://example.com',
            link_id=custom_id
        )

        assert link.id == custom_id
    
    def test_increment_clicks_updates_counter_and_timestamp(self):
        """Тест увелечения счетчиков кликов"""
        link = Link.create(
            url_hash="hash123",
            short_code='code123',
            original_url='https://example.com'
        )

        # mock datetime для фиксированного времени
        with patch('src.link_shortener.domain.entities.link.datetime') as mock_datetime:
            fixed_time = datetime(2026, 2, 5, 0, 0)
            mock_datetime.now.return_value = fixed_time

            link.increment_clicks()
        
        assert link.clicks == 1
        assert link.last_accessed == fixed_time
    
    @pytest.mark.parametrize('clicks, threshold, expected', [
        (50, 100, False), # меньше порога
        (100, 100, False), # Равно порогу (строго больше)
        (101, 100, True), # Больше порога
        (1000, 500, True), # Значительно больше порога
    ])
    def test_is_popular_with_different_thresholds(self, clicks, threshold, expected):
        """Параметризованный тест популярности ссылки"""
        link = Link.create(
            url_hash="hash123",
            short_code='code123',
            original_url='https://example.com'
        )

        link.clicks = clicks

        result = link.is_popular(threshold=threshold)

        assert result == expected
    
    def test_is_recrent_for_new_link(self):
        """Тест проверки новизны ссылки"""
        with patch('src.link_shortener.domain.entities.link.datetime') as mock_datetime:
            now = datetime(2026, 2, 5, 0, 0)
            mock_datetime.now.return_value = now

            link = Link.create(
                url_hash="abc123",
                short_code='short',
                original_url='https://example.com'
            )

            link.created_at = now

            assert link.is_recent(days=7) is True # 0 days

            link.created_at = now - timedelta(days=7)
            assert link.is_recent(days=7) is True # 7 days

            link.created_at = now - timedelta(days=8)
            assert link.is_recent(days=7) is False # 8 > 7 days
    
    def test_get_short_url_constructs_correct_url(self):
        """тест формирования сокращенной ссылки"""
        link = Link.create(
            url_hash="abc123",
            short_code='short',
            original_url='https://example.com/test'
        )

        result_1 = link.get_short_url('https:shortener.cc/')

        assert result_1 == 'https:shortener.cc/short'
    
    def test_equality_based_on_id(self):
        """тест сравнения ссылок по ID"""

        # ссылка_1
        link_1 = Link(
            id='same-id',
            url_hash='hash_1',
            short_code='code1',
            original_url='https://example1.com',
            created_at=datetime.now(),
            clicks=0
        )

        # Ссылка_2, с id ссылки_1
        link_2 = Link(
            id='same-id',
            url_hash='hash_2',
            short_code='code2',
            original_url='https://example2.com',
            created_at=datetime.now(),
            clicks=100
        )

        # Ссылка_3, с другим id, но такими же компонентами как в ссылке_1
        link_3 = Link(
            id='different-id',
            url_hash='hash_1',
            short_code='code1',
            original_url='https://example1.com',
            created_at=datetime.now(),
            clicks=0
        )

        assert link_1 == link_2
        assert link_1 != link_3
        assert link_1 != 'not_a_link'
    
    def test_hash_based_on_id(self):
        """Тест хэширования ссылки"""
        link = Link(
            id='same-id',
            url_hash='hash_1',
            short_code='code1',
            original_url='https://example1.com',
            created_at=datetime.now(),
            clicks=0
        )

        assert hash(link) == hash('same-id')

        # Использование как ключа словаря
        dicttionary = {link: 'value'}
        assert dicttionary[link] == 'value'

    def test_link_string_representation(self):
        """тест строкового представления ссылки"""
        link = Link.create(
            url_hash="abc123",
            short_code='short',
            original_url='https://example.com'
        )

        str_repr = str(link)

        assert "abc123" in str_repr
        assert 'https://example.com' in str_repr
    
    def test_link_attrubute_immutable(self):
        """Тест изменяемости атрибутов ссылки"""
        link = Link.create(
            url_hash="hash1",
            short_code='short1',
            original_url='https://first.com'
        )

        link.url_hash = 'other_hash'
        link.short_code = 'other_code'
        link.original_url = 'https://second.com'
        link.clicks = 100

        assert link.url_hash == 'other_hash'
        assert link.short_code == 'other_code'
        assert link.original_url == 'https://second.com'
        assert link.clicks == 100