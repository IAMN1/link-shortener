from link_shortener.domain.value_objects.short_code import ShortCode
from link_shortener.domain.exceptions import ValidationError
import pytest


# ------------------------------------------------------------------
# TestShortCode
# ------------------------------------------------------------------
class TestShortCode:
    """Tests for the ShortCode value object."""

    @pytest.mark.parametrize('valid_code', [
        'abc123',
        'ABC_DEF',
        '1234567890',
        'a-b_c-d_e'
    ])
    def test_valid_code_creates_object(self, valid_code):
        """Should create a ShortCode object from a valid code string."""

        code = ShortCode(valid_code)

        assert code.value == valid_code
    
    @pytest.mark.parametrize('invalid_code',[
        'abc', # < 6
        'superverylongcode', # > 10
        'abc@123', # bad symbol - @
        'Ра_Си_Я', # not ascii
        'abc123\n',   # trailing newline: "$" used to match before it
        'abc123\n\n',
        'abc123\r\n',
    ])
    def test_invalid_code_raises_value_error(self, invalid_code):
        """
        Should raise ValidationError with appropriate message for invalid code.
        """
        with pytest.raises(ValidationError, match='Invalid short code format'):
            ShortCode(invalid_code)
    
    def test_a_trailing_newline_is_not_the_same_code(self):
        """
        ``re.match(r"^...$")`` accepted ``"abc123\\n"``, because "$" in
        Python matches before a trailing newline as well as at the end. Two
        strings then validated as the same code while comparing unequal --
        harmless while lookup and deletion each work on one string, and a
        mine under any future comparison of codes or under a cache key
        built from one.
        """
        with pytest.raises(ValidationError):
            ShortCode('abc123\n')

    def test_create_method(self, valid_short_code_str):
        """Should create a ShortCode using the factory method 'create'."""
        code = ShortCode(valid_short_code_str)

        assert isinstance(code, ShortCode)
        assert code.value == valid_short_code_str