"""Tests for call memory prompt builder — TDD.

Tests the pure formatting function (_format_memory_section) extensively,
plus async build_call_memory_prompt with mocked DB.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# Import will work after implementation exists
from app.services.call_memory import _format_memory_section

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 3, 30, 12, 0, 0, tzinfo=timezone.utc)
_ORG_ID = uuid.uuid4()
_BOT_ID = uuid.uuid4()


def _make_row(
    summary="Contact was interested in coaching.",
    outcome="interested",
    call_duration=120,
    created_at=None,
    metadata_=None,
    # Analytics fields (None = no analytics row)
    goal_outcome=None,
    sentiment=None,
    lead_temperature=None,
    captured_data=None,
    objections=None,
    red_flags=None,
    has_red_flags=False,
    buying_signals=None,
):
    """Create a (CallLog-like, CallAnalytics-like|None) tuple."""
    call = SimpleNamespace(
        created_at=created_at or (_NOW - timedelta(days=3)),
        call_duration=call_duration,
        summary=summary,
        outcome=outcome,
        metadata_=metadata_ or {},
        bot_id=_BOT_ID,
    )
    has_any_analytics = any(
        v is not None
        for v in [goal_outcome, sentiment, lead_temperature, captured_data, objections, red_flags, buying_signals]
    ) or has_red_flags
    analytics = None
    if has_any_analytics:
        analytics = SimpleNamespace(
            goal_outcome=goal_outcome,
            sentiment=sentiment,
            lead_temperature=lead_temperature,
            captured_data=captured_data,
            objections=objections,
            red_flags=red_flags,
            has_red_flags=has_red_flags,
            buying_signals=buying_signals,
        )
    return (call, analytics)


# ---------------------------------------------------------------------------
# Tests — _format_memory_section (pure function, no DB)
# ---------------------------------------------------------------------------


class TestFormatMemorySection:
    """Tests for the pure formatting function."""

    def test_empty_rows_returns_empty(self):
        assert _format_memory_section([], now=_NOW) == ""

    def test_single_call_includes_summary(self):
        rows = [_make_row(summary="Contact liked the product.")]
        result = _format_memory_section(rows, now=_NOW)
        assert "Contact liked the product." in result

    def test_call_count_shown(self):
        rows = [_make_row()]
        result = _format_memory_section(rows, now=_NOW)
        assert "1 time(s) before" in result

    def test_multiple_calls_correct_count(self):
        rows = [_make_row(), _make_row()]
        result = _format_memory_section(rows, now=_NOW)
        assert "2 time(s) before" in result

    # --- Outcome ---

    def test_outcome_from_analytics(self):
        rows = [_make_row(goal_outcome="interested")]
        result = _format_memory_section(rows, now=_NOW)
        assert "Outcome: interested" in result

    def test_outcome_fallback_to_call_log(self):
        """No analytics → use CallLog.outcome."""
        rows = [_make_row(outcome="callback_requested")]
        result = _format_memory_section(rows, now=_NOW)
        assert "callback_requested" in result

    def test_outcome_analytics_preferred_over_call_log(self):
        """Analytics goal_outcome takes precedence over CallLog.outcome."""
        rows = [_make_row(outcome="unknown", goal_outcome="interested")]
        result = _format_memory_section(rows, now=_NOW)
        assert "Outcome: interested" in result
        assert "Outcome: unknown" not in result

    # --- Sentiment ---

    def test_sentiment_included(self):
        rows = [_make_row(sentiment="negative")]
        result = _format_memory_section(rows, now=_NOW)
        assert "negative" in result.lower()

    def test_negative_sentiment_cautious_instruction(self):
        rows = [_make_row(sentiment="negative")]
        result = _format_memory_section(rows, now=_NOW)
        assert any(
            word in result.lower()
            for word in ["cautious", "gently", "careful"]
        )

    # --- Interest / Lead Temperature ---

    def test_interest_level_included(self):
        rows = [_make_row(lead_temperature="hot")]
        result = _format_memory_section(rows, now=_NOW)
        assert "hot" in result.lower()

    # --- Captured Data ---

    def test_captured_data_rendered_as_known_facts(self):
        rows = [_make_row(captured_data={"profession": "Software Engineer", "company": "Google"})]
        result = _format_memory_section(rows, now=_NOW)
        assert "KNOWN FACTS" in result
        assert "Software Engineer" in result
        assert "Google" in result

    def test_captured_data_keys_humanized(self):
        """Underscored keys should be title-cased."""
        rows = [_make_row(captured_data={"monthly_budget": "$500"})]
        result = _format_memory_section(rows, now=_NOW)
        assert "Monthly Budget" in result

    def test_consolidated_facts_latest_wins(self):
        """Captured data from multiple calls merged, latest overrides."""
        rows = [
            _make_row(
                created_at=_NOW - timedelta(days=5),
                captured_data={"profession": "Teacher", "city": "Mumbai"},
            ),
            _make_row(
                created_at=_NOW - timedelta(days=2),
                captured_data={"profession": "Engineer", "budget": "$500"},
            ),
        ]
        result = _format_memory_section(rows, now=_NOW)
        assert "Engineer" in result  # latest wins
        assert "Mumbai" in result  # older preserved
        assert "$500" in result
        # Teacher should NOT appear (overridden by Engineer)
        assert "Teacher" not in result

    def test_no_known_facts_section_when_empty(self):
        rows = [_make_row(captured_data=None)]
        result = _format_memory_section(rows, now=_NOW)
        assert "KNOWN FACTS" not in result

    # --- Objections ---

    def test_objections_rendered(self):
        rows = [_make_row(objections=[
            {"category": "price", "text": "Too expensive", "resolved": False},
            {"category": "timing", "text": "Not the right time", "resolved": True},
        ])]
        result = _format_memory_section(rows, now=_NOW)
        assert "Too expensive" in result
        assert "unresolved" in result.lower()
        assert "Not the right time" in result
        assert "resolved" in result.lower()

    def test_no_objections_section_when_empty(self):
        rows = [_make_row(objections=None)]
        result = _format_memory_section(rows, now=_NOW)
        assert "OBJECTIONS" not in result

    # --- Red Flags ---

    def test_red_flags_warning(self):
        rows = [_make_row(
            red_flags=[{"id": "customer_angry", "severity": "high", "evidence": "Raised voice"}],
            has_red_flags=True,
        )]
        result = _format_memory_section(rows, now=_NOW)
        assert "customer_angry" in result
        assert "high" in result.lower()

    def test_no_red_flags_section_when_clean(self):
        rows = [_make_row(red_flags=None, has_red_flags=False)]
        result = _format_memory_section(rows, now=_NOW)
        assert "RED FLAGS" not in result

    # --- Buying Signals ---

    def test_buying_signals_included(self):
        rows = [_make_row(buying_signals=["Asked about pricing", "Requested demo"])]
        result = _format_memory_section(rows, now=_NOW)
        assert "Asked about pricing" in result
        assert "Requested demo" in result

    def test_no_buying_signals_section_when_empty(self):
        rows = [_make_row(buying_signals=None)]
        result = _format_memory_section(rows, now=_NOW)
        assert "BUYING SIGNALS" not in result

    # --- Time Since Last Call ---

    def test_recency_days(self):
        rows = [_make_row(created_at=_NOW - timedelta(days=3))]
        result = _format_memory_section(rows, now=_NOW)
        assert "3 days ago" in result

    def test_recency_yesterday(self):
        rows = [_make_row(created_at=_NOW - timedelta(days=1))]
        result = _format_memory_section(rows, now=_NOW)
        assert "yesterday" in result

    def test_recency_today(self):
        rows = [_make_row(created_at=_NOW - timedelta(hours=2))]
        result = _format_memory_section(rows, now=_NOW)
        assert "earlier today" in result

    def test_recency_weeks(self):
        rows = [_make_row(created_at=_NOW - timedelta(days=14))]
        result = _format_memory_section(rows, now=_NOW)
        assert "2 week" in result

    def test_recency_months(self):
        rows = [_make_row(created_at=_NOW - timedelta(days=45))]
        result = _format_memory_section(rows, now=_NOW)
        assert "month" in result.lower()

    def test_recent_followup_casual_framing(self):
        """<= 3 days → casual follow-up."""
        rows = [_make_row(created_at=_NOW - timedelta(days=1))]
        result = _format_memory_section(rows, now=_NOW)
        assert "recent" in result.lower() or "pick up" in result.lower()

    def test_old_call_reestablish_framing(self):
        """> 30 days → re-establish."""
        rows = [_make_row(created_at=_NOW - timedelta(days=35))]
        result = _format_memory_section(rows, now=_NOW)
        assert "re-introduce" in result.lower() or "over a month" in result.lower()

    # --- Duration Formatting ---

    def test_duration_formatted_minutes_seconds(self):
        rows = [_make_row(call_duration=185)]
        result = _format_memory_section(rows, now=_NOW)
        assert "3m 5s" in result

    def test_duration_seconds_only(self):
        rows = [_make_row(call_duration=45)]
        result = _format_memory_section(rows, now=_NOW)
        assert "45s" in result

    def test_duration_unknown(self):
        rows = [_make_row(call_duration=None)]
        result = _format_memory_section(rows, now=_NOW)
        assert "Unknown" in result

    # --- Short Call Framing ---

    def test_short_call_noted(self):
        """< 30s call should be flagged as brief."""
        rows = [_make_row(call_duration=15)]
        result = _format_memory_section(rows, now=_NOW)
        assert "brief" in result.lower()

    # --- Anti-Hallucination Rules ---

    def test_no_hallucination_claim(self):
        """Must NOT tell bot it 'remembers everything' or has 'full notes'."""
        rows = [_make_row()]
        result = _format_memory_section(rows, now=_NOW)
        assert "You DO remember" not in result
        assert "you have full notes" not in result
        assert "remember everything" not in result

    def test_only_reference_listed_data_rule(self):
        """Must instruct bot to only use data explicitly provided."""
        rows = [_make_row()]
        result = _format_memory_section(rows, now=_NOW)
        lower = result.lower()
        assert ("only" in lower and ("listed" in lower or "provided" in lower or "shown" in lower))

    # --- Chronological Order ---

    def test_chronological_order_preserved(self):
        rows = [
            _make_row(created_at=_NOW - timedelta(days=5), summary="First call."),
            _make_row(created_at=_NOW - timedelta(days=2), summary="Second call."),
        ]
        result = _format_memory_section(rows, now=_NOW)
        assert result.index("First call.") < result.index("Second call.")

    # --- Graceful Degradation ---

    def test_no_analytics_row_still_works(self):
        """Call with no analytics → renders summary + CallLog fields only."""
        rows = [_make_row()]
        result = _format_memory_section(rows, now=_NOW)
        assert "Contact was interested in coaching." in result

    def test_analytics_with_all_none_fields(self):
        """Analytics row exists but all fields None → no crash, no empty sections."""
        analytics = SimpleNamespace(
            goal_outcome=None, sentiment=None, lead_temperature=None,
            captured_data=None, objections=None, red_flags=None,
            has_red_flags=False, buying_signals=None,
        )
        call = SimpleNamespace(
            created_at=_NOW - timedelta(days=1),
            call_duration=60, summary="Short call.", outcome=None,
            metadata_={}, bot_id=_BOT_ID,
        )
        rows = [(call, analytics)]
        result = _format_memory_section(rows, now=_NOW)
        assert "Short call." in result
        assert "KNOWN FACTS" not in result
        assert "OBJECTIONS" not in result
        assert "RED FLAGS" not in result

    # --- Smoke Test: All Fields Populated ---

    def test_full_data_smoke_test(self):
        rows = [_make_row(
            summary="Great conversation about coaching.",
            outcome="interested",
            call_duration=300,
            goal_outcome="interested",
            sentiment="positive",
            lead_temperature="hot",
            captured_data={"profession": "Doctor", "budget": "$1000"},
            objections=[{"category": "timing", "text": "Busy this month", "resolved": False}],
            red_flags=[{"id": "pressure_tactics", "severity": "medium"}],
            has_red_flags=True,
            buying_signals=["Asked for contract details"],
        )]
        result = _format_memory_section(rows, now=_NOW)
        assert "Doctor" in result
        assert "$1000" in result
        assert "Busy this month" in result
        assert "pressure_tactics" in result
        assert "Asked for contract details" in result
        assert "positive" in result.lower()
        assert "hot" in result.lower()
        assert "Outcome: interested" in result
