"""
Tests for goal-aware CallAnalyzer.

These tests validate that the analyzer correctly classifies outcomes,
detects red flags, and extracts structured data from transcripts.

Marked as @pytest.mark.slow because they make real Gemini API calls.
Run with: pytest tests/test_call_analyzer.py -m slow -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "transcripts" / "event_invitation"


def load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


def load_goal_config() -> dict:
    with open(FIXTURES_DIR / "goal_config.json") as f:
        return json.load(f)


# Will be importable after Phase 2 implementation
# from app.services.call_analyzer import CallAnalyzer


@pytest.fixture
def goal_config():
    return load_goal_config()


@pytest.fixture
def analyzer():
    # TODO: Uncomment after Phase 2 implementation
    # return CallAnalyzer()
    pytest.skip("CallAnalyzer not yet implemented")


# --- Outcome Classification Tests ---


@pytest.mark.slow
@pytest.mark.asyncio
async def test_outcome_confirmed_clear(analyzer, goal_config):
    """Clear confirmation should be classified as 'confirmed'."""
    fixture = load_fixture("01_confirmed_clear.json")
    result = await analyzer.analyze(
        transcript=fixture["transcript"],
        goal_config=goal_config,
        system_prompt="",
    )
    assert result.goal_outcome == "confirmed"
    assert result.interest_level == "high"
    assert len(result.red_flags) == 0


@pytest.mark.slow
@pytest.mark.asyncio
async def test_outcome_declined_busy(analyzer, goal_config):
    """Busy contact requesting callback should be 'callback'."""
    fixture = load_fixture("02_declined_busy.json")
    result = await analyzer.analyze(
        transcript=fixture["transcript"],
        goal_config=goal_config,
        system_prompt="",
    )
    assert result.goal_outcome == "callback"
    assert result.interest_level in ("medium", "low")


@pytest.mark.slow
@pytest.mark.asyncio
async def test_outcome_hostile_dnd(analyzer, goal_config):
    """Hostile caller with DND should be 'declined' with critical red flags."""
    fixture = load_fixture("03_hostile_dnd.json")
    result = await analyzer.analyze(
        transcript=fixture["transcript"],
        goal_config=goal_config,
        system_prompt="",
    )
    assert result.goal_outcome == "declined"
    assert result.interest_level == "low"

    flag_ids = {rf["id"] for rf in result.red_flags}
    assert "dnd" in flag_ids
    # At least one critical flag
    assert any(rf["severity"] == "critical" for rf in result.red_flags)


@pytest.mark.slow
@pytest.mark.asyncio
async def test_outcome_ambiguous_tentative(analyzer, goal_config):
    """'I'll try to come' should be classified as 'tentative', not 'confirmed'."""
    fixture = load_fixture("04_ambiguous_try_to_come.json")
    result = await analyzer.analyze(
        transcript=fixture["transcript"],
        goal_config=goal_config,
        system_prompt="",
    )
    assert result.goal_outcome == "tentative"
    assert result.interest_level == "medium"


@pytest.mark.slow
@pytest.mark.asyncio
async def test_outcome_declined_already_attended(analyzer, goal_config):
    """Already-attended contact declining should be 'declined' with competitor mention flag."""
    fixture = load_fixture("05_declined_already_attended.json")
    result = await analyzer.analyze(
        transcript=fixture["transcript"],
        goal_config=goal_config,
        system_prompt="",
    )
    assert result.goal_outcome == "declined"

    flag_ids = {rf["id"] for rf in result.red_flags}
    assert "competitor_mention" in flag_ids


# --- Data Extraction Tests ---


@pytest.mark.slow
@pytest.mark.asyncio
async def test_data_extraction_enum_constrained(analyzer, goal_config):
    """Extracted enum fields should only contain values from enum_values list."""
    fixture = load_fixture("01_confirmed_clear.json")
    result = await analyzer.analyze(
        transcript=fixture["transcript"],
        goal_config=goal_config,
        system_prompt="",
    )
    valid_attendees = {"1", "2", "3", "4", "5+"}
    if result.captured_data.get("num_attendees") is not None:
        assert result.captured_data["num_attendees"] in valid_attendees

    valid_objections = {"busy_schedule", "not_interested", "cost_concern",
                        "already_attended", "location_issue", "other", None}
    assert result.captured_data.get("objection_reason") in valid_objections


@pytest.mark.slow
@pytest.mark.asyncio
async def test_data_extraction_objection_reason(analyzer, goal_config):
    """Declined calls should capture the correct objection reason."""
    fixture = load_fixture("05_declined_already_attended.json")
    result = await analyzer.analyze(
        transcript=fixture["transcript"],
        goal_config=goal_config,
        system_prompt="",
    )
    assert result.captured_data.get("objection_reason") == "already_attended"


# --- Red Flag Merge Tests ---


def test_red_flag_merge_deduplication():
    """Real-time flags should take priority over post-call duplicates."""
    # This test doesn't need the LLM — tests the merge logic directly
    # TODO: Import after Phase 2
    # from app.services.call_analyzer import CallAnalyzer
    # analyzer = CallAnalyzer()

    realtime_flags = [
        {"id": "dnd", "severity": "critical", "evidence": "stop calling me", "turn_index": 3}
    ]
    postcard_flags = [
        {"id": "dnd", "severity": "critical", "evidence": "don't call me again"},
        {"id": "complaint", "severity": "high", "evidence": "file a complaint"}
    ]

    # TODO: Uncomment after Phase 2
    # merged = analyzer._merge_red_flags(realtime_flags, postcard_flags)
    # assert len(merged) == 2  # dnd (from realtime) + complaint (from post-call)
    # dnd_flag = next(f for f in merged if f["id"] == "dnd")
    # assert dnd_flag["turn_index"] == 3  # From realtime, not post-call
    pytest.skip("CallAnalyzer not yet implemented")


# --- Fallback Tests ---


@pytest.mark.slow
@pytest.mark.asyncio
async def test_fallback_generic_no_goal_config(analyzer):
    """When goal_config is None, should fall back to generic summary + interest."""
    fixture = load_fixture("01_confirmed_clear.json")
    result = await analyzer.analyze(
        transcript=fixture["transcript"],
        goal_config=None,
        system_prompt="",
    )
    # Should still produce summary and interest_level
    assert result.summary is not None
    assert result.interest_level in ("high", "medium", "low")
    # Goal-specific fields should be empty/None
    assert result.goal_outcome is None
    assert result.red_flags == []
    assert result.captured_data == {}
