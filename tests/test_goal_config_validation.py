"""
Tests for GoalConfig Pydantic validation.

These tests run without any external services — pure validation logic.
Run with: pytest tests/test_goal_config_validation.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# TODO: Uncomment after Phase 1 implementation
# from app.models.schemas import GoalConfig, RedFlagConfig, SuccessCriterion, DataCaptureField

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "transcripts" / "event_invitation"


def _skip_if_not_implemented():
    try:
        from app.models.schemas import GoalConfig  # noqa: F401
    except ImportError:
        pytest.skip("GoalConfig not yet implemented")


class TestValidConfigs:
    def test_valid_event_invitation_config(self):
        """The fixture goal_config.json should pass validation."""
        _skip_if_not_implemented()
        from app.models.schemas import GoalConfig

        with open(FIXTURES_DIR / "goal_config.json") as f:
            data = json.load(f)
        config = GoalConfig(**data)
        assert config.version == 1
        assert config.goal_type == "event_invitation"
        assert len(config.success_criteria) == 5
        assert sum(1 for c in config.success_criteria if c.is_primary) == 1

    def test_minimal_valid_config(self):
        """Minimal config with just required fields should pass."""
        _skip_if_not_implemented()
        from app.models.schemas import GoalConfig

        config = GoalConfig(
            goal_type="simple",
            goal_description="Test goal",
            success_criteria=[
                {"id": "done", "label": "Done", "is_primary": True},
            ],
        )
        assert config.version == 1
        assert config.red_flags == []
        assert config.data_capture_fields == []


class TestPrimaryValidation:
    def test_no_primary_criterion_rejected(self):
        """Config with no primary success criterion should be rejected."""
        _skip_if_not_implemented()
        from app.models.schemas import GoalConfig

        with pytest.raises(Exception):  # ValidationError
            GoalConfig(
                goal_type="test",
                goal_description="No primary",
                success_criteria=[
                    {"id": "a", "label": "A", "is_primary": False},
                    {"id": "b", "label": "B", "is_primary": False},
                ],
            )

    def test_multiple_primary_criteria_rejected(self):
        """Config with multiple primary criteria should be rejected."""
        _skip_if_not_implemented()
        from app.models.schemas import GoalConfig

        with pytest.raises(Exception):  # ValidationError
            GoalConfig(
                goal_type="test",
                goal_description="Two primaries",
                success_criteria=[
                    {"id": "a", "label": "A", "is_primary": True},
                    {"id": "b", "label": "B", "is_primary": True},
                ],
            )


class TestUniqueIds:
    def test_duplicate_criterion_ids_rejected(self):
        """Duplicate IDs across success criteria should be rejected."""
        _skip_if_not_implemented()
        from app.models.schemas import GoalConfig

        with pytest.raises(Exception):
            GoalConfig(
                goal_type="test",
                goal_description="Duplicate IDs",
                success_criteria=[
                    {"id": "same", "label": "A", "is_primary": True},
                    {"id": "same", "label": "B", "is_primary": False},
                ],
            )

    def test_duplicate_ids_across_types_rejected(self):
        """Duplicate IDs across criteria, flags, and fields should be rejected."""
        _skip_if_not_implemented()
        from app.models.schemas import GoalConfig

        with pytest.raises(Exception):
            GoalConfig(
                goal_type="test",
                goal_description="Cross-type duplicates",
                success_criteria=[
                    {"id": "shared_id", "label": "Criterion", "is_primary": True},
                ],
                red_flags=[
                    {"id": "shared_id", "label": "Flag", "severity": "high"},
                ],
            )


class TestRedFlagValidation:
    def test_realtime_without_keywords_rejected(self):
        """Red flag with detect_in='realtime' but no keywords should be rejected."""
        _skip_if_not_implemented()
        from app.models.schemas import GoalConfig

        with pytest.raises(Exception) as exc_info:
            GoalConfig(
                goal_type="test",
                goal_description="Realtime without keywords",
                success_criteria=[
                    {"id": "done", "label": "Done", "is_primary": True},
                ],
                red_flags=[
                    {"id": "bad_flag", "label": "Bad", "severity": "high",
                     "detect_in": "realtime", "keywords": None},
                ],
            )
        assert "realtime" in str(exc_info.value).lower() or "keywords" in str(exc_info.value).lower()

    def test_realtime_with_empty_keywords_rejected(self):
        """Red flag with detect_in='realtime' but empty keywords list should be rejected."""
        _skip_if_not_implemented()
        from app.models.schemas import GoalConfig

        with pytest.raises(Exception):
            GoalConfig(
                goal_type="test",
                goal_description="Realtime empty keywords",
                success_criteria=[
                    {"id": "done", "label": "Done", "is_primary": True},
                ],
                red_flags=[
                    {"id": "bad_flag", "label": "Bad", "severity": "high",
                     "detect_in": "realtime", "keywords": []},
                ],
            )

    def test_post_call_without_keywords_accepted(self):
        """Red flag with detect_in='post_call' and no keywords should be accepted."""
        _skip_if_not_implemented()
        from app.models.schemas import GoalConfig

        config = GoalConfig(
            goal_type="test",
            goal_description="Post-call without keywords",
            success_criteria=[
                {"id": "done", "label": "Done", "is_primary": True},
            ],
            red_flags=[
                {"id": "semantic_flag", "label": "Semantic", "severity": "medium",
                 "detect_in": "post_call"},
            ],
        )
        assert len(config.red_flags) == 1


class TestDataCaptureFieldValidation:
    def test_enum_without_values_rejected(self):
        """Data capture field with type='enum' but no enum_values should be rejected."""
        _skip_if_not_implemented()
        from app.models.schemas import GoalConfig

        with pytest.raises(Exception) as exc_info:
            GoalConfig(
                goal_type="test",
                goal_description="Enum without values",
                success_criteria=[
                    {"id": "done", "label": "Done", "is_primary": True},
                ],
                data_capture_fields=[
                    {"id": "broken_field", "label": "Broken", "type": "enum"},
                ],
            )
        assert "enum" in str(exc_info.value).lower()

    def test_string_without_enum_values_accepted(self):
        """Data capture field with type='string' and no enum_values should be accepted."""
        _skip_if_not_implemented()
        from app.models.schemas import GoalConfig

        config = GoalConfig(
            goal_type="test",
            goal_description="String field",
            success_criteria=[
                {"id": "done", "label": "Done", "is_primary": True},
            ],
            data_capture_fields=[
                {"id": "free_text", "label": "Notes", "type": "string"},
            ],
        )
        assert len(config.data_capture_fields) == 1


class TestVersionField:
    def test_version_defaults_to_1(self):
        """Version should default to 1 when not specified."""
        _skip_if_not_implemented()
        from app.models.schemas import GoalConfig

        config = GoalConfig(
            goal_type="test",
            goal_description="No version",
            success_criteria=[
                {"id": "done", "label": "Done", "is_primary": True},
            ],
        )
        assert config.version == 1

    def test_explicit_version(self):
        """Explicit version should be preserved."""
        _skip_if_not_implemented()
        from app.models.schemas import GoalConfig

        config = GoalConfig(
            version=2,
            goal_type="test",
            goal_description="Version 2",
            success_criteria=[
                {"id": "done", "label": "Done", "is_primary": True},
            ],
        )
        assert config.version == 2
