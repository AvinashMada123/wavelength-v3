"""Comprehensive unit tests for n8n webhook condition evaluator."""

import sys
from types import SimpleNamespace

sys.modules.setdefault(
    "structlog",
    SimpleNamespace(
        get_logger=lambda *a, **kw: SimpleNamespace(
            info=lambda *a, **kw: None,
            warning=lambda *a, **kw: None,
            error=lambda *a, **kw: None,
            debug=lambda *a, **kw: None,
        )
    ),
)

import pytest

from app.services.n8n_webhook import _eval_single, _resolve_field, evaluate_conditions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cond(field: str, operator: str, value=None) -> dict:
    """Shorthand to build a condition dict."""
    return {"field": field, "operator": operator, "value": value}


SAMPLE_DATA = {
    "outcome": "completed",
    "sentiment": "positive",
    "lead_temperature": "hot",
    "call_duration": 120,
    "is_voicemail": False,
    "tags": ["vip", "follow-up"],
    "captured_data": {
        "email": "a@b.com",
        "address": {"city": "Mumbai"},
    },
    "empty_str": "",
    "none_val": None,
    "empty_dict": {},
}


# ===================================================================
# equals
# ===================================================================

class TestEqualsOperator:
    def test_string_match(self):
        assert _eval_single(_cond("outcome", "equals", "completed"), SAMPLE_DATA) is True

    def test_string_mismatch(self):
        assert _eval_single(_cond("outcome", "equals", "failed"), SAMPLE_DATA) is False

    def test_case_sensitive(self):
        assert _eval_single(_cond("outcome", "equals", "Completed"), SAMPLE_DATA) is False

    def test_numeric(self):
        assert _eval_single(_cond("call_duration", "equals", 120), SAMPLE_DATA) is True

    def test_boolean(self):
        assert _eval_single(_cond("is_voicemail", "equals", False), SAMPLE_DATA) is True

    def test_none_equals_none(self):
        assert _eval_single(_cond("none_val", "equals", None), SAMPLE_DATA) is True

    def test_missing_field_equals_none(self):
        assert _eval_single(_cond("no_such_field", "equals", None), SAMPLE_DATA) is True


# ===================================================================
# not_equals
# ===================================================================

class TestNotEqualsOperator:
    def test_different_values(self):
        assert _eval_single(_cond("outcome", "not_equals", "failed"), SAMPLE_DATA) is True

    def test_same_value(self):
        assert _eval_single(_cond("outcome", "not_equals", "completed"), SAMPLE_DATA) is False

    def test_missing_field_not_equals_string(self):
        assert _eval_single(_cond("missing", "not_equals", "x"), SAMPLE_DATA) is True

    def test_none_not_equals_value(self):
        assert _eval_single(_cond("none_val", "not_equals", "something"), SAMPLE_DATA) is True


# ===================================================================
# in
# ===================================================================

class TestInOperator:
    def test_present_in_list(self):
        assert _eval_single(_cond("outcome", "in", ["completed", "failed"]), SAMPLE_DATA) is True

    def test_absent_from_list(self):
        assert _eval_single(_cond("outcome", "in", ["failed", "cancelled"]), SAMPLE_DATA) is False

    def test_single_element_list(self):
        assert _eval_single(_cond("outcome", "in", ["completed"]), SAMPLE_DATA) is True

    def test_none_in_list_with_none(self):
        assert _eval_single(_cond("none_val", "in", [None, "x"]), SAMPLE_DATA) is True

    def test_value_not_a_list_returns_false(self):
        """When expected is not a list, operator should return False."""
        assert _eval_single(_cond("outcome", "in", "completed"), SAMPLE_DATA) is False


# ===================================================================
# not_in
# ===================================================================

class TestNotInOperator:
    def test_absent_from_list(self):
        assert _eval_single(_cond("outcome", "not_in", ["failed", "cancelled"]), SAMPLE_DATA) is True

    def test_present_in_list(self):
        assert _eval_single(_cond("outcome", "not_in", ["completed", "failed"]), SAMPLE_DATA) is False

    def test_missing_field_not_in_list(self):
        """Missing field resolves to None; None not in list → True."""
        assert _eval_single(_cond("missing", "not_in", ["a", "b"]), SAMPLE_DATA) is True


# ===================================================================
# contains
# ===================================================================

class TestContainsOperator:
    def test_substring_match(self):
        assert _eval_single(_cond("outcome", "contains", "complet"), SAMPLE_DATA) is True

    def test_substring_no_match(self):
        assert _eval_single(_cond("outcome", "contains", "xyz"), SAMPLE_DATA) is False

    def test_case_sensitive(self):
        assert _eval_single(_cond("outcome", "contains", "Complet"), SAMPLE_DATA) is False

    def test_list_membership(self):
        assert _eval_single(_cond("tags", "contains", "vip"), SAMPLE_DATA) is True

    def test_none_field_returns_false(self):
        assert _eval_single(_cond("none_val", "contains", "x"), SAMPLE_DATA) is False

    def test_empty_string_contains_empty(self):
        """Empty string contains empty substring (standard Python behavior)."""
        assert _eval_single(_cond("empty_str", "contains", ""), SAMPLE_DATA) is True


# ===================================================================
# exists
# ===================================================================

class TestExistsOperator:
    def test_truthy_value(self):
        assert _eval_single(_cond("outcome", "exists"), SAMPLE_DATA) is True

    def test_none_value(self):
        assert _eval_single(_cond("none_val", "exists"), SAMPLE_DATA) is False

    def test_missing_field(self):
        assert _eval_single(_cond("no_such_field", "exists"), SAMPLE_DATA) is False

    def test_empty_string(self):
        assert _eval_single(_cond("empty_str", "exists"), SAMPLE_DATA) is False

    def test_empty_dict(self):
        assert _eval_single(_cond("empty_dict", "exists"), SAMPLE_DATA) is False


# ===================================================================
# Dot-notation field resolver
# ===================================================================

class TestDotNotationAccess:
    def test_single_level(self):
        assert _resolve_field("outcome", SAMPLE_DATA) == "completed"

    def test_nested(self):
        assert _resolve_field("captured_data.email", SAMPLE_DATA) == "a@b.com"

    def test_missing_intermediate(self):
        assert _resolve_field("captured_data.phone.ext", SAMPLE_DATA) is None

    def test_non_dict_intermediate(self):
        """Traversing through a non-dict value returns None."""
        assert _resolve_field("outcome.sub", SAMPLE_DATA) is None

    def test_top_level_missing(self):
        assert _resolve_field("nope", SAMPLE_DATA) is None


# ===================================================================
# Condition logic (all / any)
# ===================================================================

class TestConditionLogic:
    def test_all_true(self):
        conds = [
            _cond("outcome", "equals", "completed"),
            _cond("sentiment", "equals", "positive"),
        ]
        assert evaluate_conditions(conds, "all", SAMPLE_DATA) is True

    def test_all_one_false(self):
        conds = [
            _cond("outcome", "equals", "completed"),
            _cond("sentiment", "equals", "negative"),
        ]
        assert evaluate_conditions(conds, "all", SAMPLE_DATA) is False

    def test_any_one_true(self):
        conds = [
            _cond("outcome", "equals", "failed"),
            _cond("sentiment", "equals", "positive"),
        ]
        assert evaluate_conditions(conds, "any", SAMPLE_DATA) is True

    def test_any_all_false(self):
        conds = [
            _cond("outcome", "equals", "failed"),
            _cond("sentiment", "equals", "negative"),
        ]
        assert evaluate_conditions(conds, "any", SAMPLE_DATA) is False

    def test_empty_conditions(self):
        assert evaluate_conditions([], None, SAMPLE_DATA) is True

    def test_none_conditions(self):
        assert evaluate_conditions(None, None, SAMPLE_DATA) is True

    def test_default_logic_is_all(self):
        """When condition_logic is None, defaults to 'all'."""
        conds = [
            _cond("outcome", "equals", "completed"),
            _cond("sentiment", "equals", "negative"),
        ]
        assert evaluate_conditions(conds, None, SAMPLE_DATA) is False


# ===================================================================
# Edge cases
# ===================================================================

class TestConditionEdgeCases:
    def test_invalid_operator(self):
        assert _eval_single(_cond("outcome", "greater_than", 5), SAMPLE_DATA) is False

    def test_empty_field_name(self):
        """Empty string field resolves against the full dict, which is truthy."""
        result = _eval_single({"field": "", "operator": "exists"}, SAMPLE_DATA)
        # _resolve_field("", data) splits "" → [""] → data.get("") → None
        assert result is False

    def test_type_mismatch_equals(self):
        """Comparing int field to string value; Python == handles this as False."""
        assert _eval_single(_cond("call_duration", "equals", "120"), SAMPLE_DATA) is False
