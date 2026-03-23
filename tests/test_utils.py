"""Tests for app.utils — phone number normalization."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault(
    "structlog", SimpleNamespace(get_logger=lambda *a, **kw: MagicMock())
)

from app.utils import normalize_phone


# ---------------------------------------------------------------------------
# Indian numbers (default)
# ---------------------------------------------------------------------------

class TestNormalizePhoneIndia:
    def test_bare_10_digits(self):
        assert normalize_phone("9609775259") == "+919609775259"

    def test_leading_zero_11_digits(self):
        assert normalize_phone("09609775259") == "+919609775259"

    def test_country_code_prefix_12_digits(self):
        assert normalize_phone("919609775259") == "+919609775259"

    def test_double_zero_prefix_10_remaining(self):
        assert normalize_phone("009609775259") == "+919609775259"

    def test_plus_91_already_e164(self):
        assert normalize_phone("+919609775259") == "+919609775259"

    def test_whitespace_stripped(self):
        assert normalize_phone("  9609775259  ") == "+919609775259"

    def test_dashes_detected_as_us_format(self):
        """Dashes trigger US-format detection → +1 prefix."""
        assert normalize_phone("960-977-5259") == "+19609775259"

    def test_dots_detected_as_us_format(self):
        """Dots trigger US-format detection → +1 prefix."""
        assert normalize_phone("960.977.5259") == "+19609775259"


# ---------------------------------------------------------------------------
# US numbers (must have formatting to be detected as US)
# ---------------------------------------------------------------------------

class TestNormalizePhoneUS:
    def test_parens_format(self):
        assert normalize_phone("(317) 712-7687") == "+13177127687"

    def test_dashes_format(self):
        assert normalize_phone("317-712-7687") == "+13177127687"

    def test_dots_format(self):
        assert normalize_phone("317.712.7687") == "+13177127687"

    def test_bare_10_digits_defaults_to_india(self):
        """Bare 10-digit without formatting → Indian, not US."""
        result = normalize_phone("3177127687")
        assert result == "+913177127687"

    def test_11_digits_starting_with_1(self):
        """11 digits starting with 1 → already has country code."""
        assert normalize_phone("13177127687") == "+13177127687"


# ---------------------------------------------------------------------------
# International / already E.164
# ---------------------------------------------------------------------------

class TestNormalizePhoneInternational:
    def test_plus_prefix_passthrough(self):
        assert normalize_phone("+442071234567") == "+442071234567"

    def test_plus_prefix_with_spaces(self):
        assert normalize_phone("+44 207 123 4567") == "+442071234567"

    def test_double_zero_international(self):
        """00 prefix with non-10-digit remainder → international."""
        assert normalize_phone("00442071234567") == "+442071234567"

    def test_long_number_without_plus(self):
        """13+ digits → assume country code included."""
        assert normalize_phone("442071234567") == "+442071234567"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestNormalizePhoneEdgeCases:
    def test_empty_after_strip(self):
        """Just whitespace → returns '+' prefix on empty."""
        result = normalize_phone("   ")
        assert result.startswith("+")

    def test_single_digit(self):
        result = normalize_phone("5")
        assert result == "+5"

    def test_all_zeros_10_digits(self):
        """Leading 0 + 10 digits → strip 0 → 9 digits (00..0) → short, returns +prefix."""
        # 0000000000 → strip leading 0 (11-digit check: len==10, starts with 0)
        # Actually: starts with "00" → strip 00 → "00000000" (8 digits) → +00000000
        assert normalize_phone("0000000000") == "+00000000"

    def test_mixed_punctuation_detected_as_us(self):
        """Parens + dashes trigger US-format detection → +1 prefix."""
        assert normalize_phone("(960) 977-5259") == "+19609775259"

    def test_parens_without_space_detected_as_us(self):
        """Parens trigger US-format detection → +1 prefix."""
        assert normalize_phone("(960)9775259") == "+19609775259"

    def test_short_number_under_10(self):
        result = normalize_phone("12345")
        assert result == "+12345"

    def test_double_zero_then_10_digits(self):
        """00 + 10 digits → stripped 00, 10 digits → Indian."""
        assert normalize_phone("001234567890") == "+911234567890"

    def test_none_input_raises_attribute_error(self):
        """None input raises AttributeError (no .strip() on None)."""
        with pytest.raises(AttributeError):
            normalize_phone(None)
