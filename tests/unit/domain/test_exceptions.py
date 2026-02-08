import pytest

from src.link_shortener.domain.exceptions import BusinessRuleError, DomainError, EntityNotFoundError, InfrastructureError, LinkNotFoundError, ValidationError


@pytest.mark.unit
class TestDomainExceptions:
    """Тесты для доменных исключений"""

    def test_domain_error_basic_functionality(self):
        """Тест базового исключения DomainError"""

        # Act
        error = DomainError(
            message='Test error',
            code='TEST_ERROR',
            details={'field': 'value'}
        )

        # Assert
        assert str(error) == 'Test error'
        assert error.message == 'Test error'
        assert error.code == 'TEST_ERROR'
        assert error.details == {'field': 'value'}
    
    def test_domain_error_with_default_values(self):
        """тест DomainError с значениями по умолчанию"""
        # Act
        error = DomainError(message='Test message error')

        # Assert
        assert error.code == 'DOMAIN_ERROR'
        assert error.details == {}
    
    def test_business_rule_error_creation(self):
        """Тест создания BusinessRuleError"""
        # Act
        error = BusinessRuleError(
            message="Link is expired",
            rule_name="expiration_rule",
            details={"expired_at": "2026-01-01"}
        )
        
        # Assert
        assert str(error) == "Link is expired"
        assert error.code == "BUSINESS_RULE_ERROR"
        assert error.rule_name == "expiration_rule"
        assert error.details == {"expired_at": "2026-01-01"}

    def test_validation_error_creation(self):
        """Тест создания ValidationError"""
        error = ValidationError(
            message='Invalid Url',
            field='original_url',
            value='invalid-url'
        )

        # Assert
        assert str(error) == 'Invalid Url'
        assert error.code == 'VALIDATION_ERROR'
        assert error.field == 'original_url'
        assert error.value == 'invalid-url'

    def test_entity_not_found_error_without_id(self):
        """Тест EntityNotFound без ID"""
        # Act
        error = EntityNotFoundError(entity_name='User')

        # Assert
        assert 'User не найдена' in str(error)
        assert error.entity_name == 'User'
        assert error.entity_id is None
    
    def test_entity_not_found_error_with_id(self):
        """Тест EntityNotFound с ID"""
        ent_name = 'User'
        ent_id = 'user-123'
        
        # Act
        error = EntityNotFoundError(
            entity_name=ent_name,
            entity_id=ent_id,
            details={'field': 'value'}
        )

        # Assert
        assert f'{ent_name} с ID "{ent_id}" не найдена' in str(error)
        assert error.entity_id == 'user-123'
        assert error.details == {'field': 'value'}
    
    def test_link_not_found_error_with_short_code(self):
        """Тест LinkNotFoundError c коротким кодом"""
        test_code = 'code1'
        
        # Act
        error = LinkNotFoundError(short_code=test_code)
        
        # Assert
        assert "Ссылка" in str(error)
        assert f'Короткий код "{test_code}"' in str(error)
        assert error.entity_name == "Ссылка"
    
    def test_link_not_found_error_with_url_hash(self):
        """Тест LinkNotFoundError с хэшем URL"""
        test_hash = 'hash1'

        # Act
        error = LinkNotFoundError(url_hash=test_hash)

        # Assert
        assert "Ссылка" in str(error)
        assert f'Хэш "{test_hash}"' in str(error)
    
    def test_infrastructure_error_creation(self):
        """Тест создания InfrastructureError"""
        # Act
        error = InfrastructureError(
            message='Database connection failed',
            service_name='PostgreSQL'
        )

        # Assert
        assert str(error) == 'Database connection failed'
        assert error.code == 'INFRASTRUCTURE_ERROR'
        assert error.service_name == 'PostgreSQL'
    
    def test_exceptions_inheritance(self):
        """Тест иерархии наследования исключений"""
        
        assert issubclass(DomainError, Exception)
        assert issubclass(BusinessRuleError, DomainError)
        assert issubclass(ValidationError, DomainError)
        assert issubclass(EntityNotFoundError, DomainError)
        assert issubclass(LinkNotFoundError, EntityNotFoundError)
        assert issubclass(InfrastructureError, DomainError)
    
    def test_exception_can_be_raised_and_caught(self):
        """Тест возможности выброса и перехвата исключений"""

        # Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            raise ValidationError(
                message='Test raise Validation error',
                field='test_field'
            )
        
        assert exc_info.value.field == 'test_field'
        assert exc_info.value.code == 'VALIDATION_ERROR'