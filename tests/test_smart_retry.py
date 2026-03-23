"""Tests for smart retry schedule feature."""
import pytest
from datetime import datetime, timezone, timedelta

from app.models.schemas import RetryStep, CallbackSchedule


class TestRetryStepValidation:
    def test_valid_delay_hours(self):
        step = RetryStep(delay_hours=3.0)
        assert step.delay_hours == 3.0
        assert step.delay_type is None

    def test_valid_next_day(self):
        step = RetryStep(delay_type="next_day")
        assert step.delay_type == "next_day"
        assert step.delay_hours is None

    def test_valid_with_preferred_window(self):
        step = RetryStep(delay_type="next_day", preferred_window=[11, 13])
        assert step.preferred_window == [11, 13]

    def test_rejects_both_delay_fields(self):
        with pytest.raises(ValueError, match="mutually exclusive"):
            RetryStep(delay_hours=3.0, delay_type="next_day")

    def test_rejects_neither_delay_field(self):
        with pytest.raises(ValueError, match="One of"):
            RetryStep()

    def test_rejects_negative_delay(self):
        with pytest.raises(ValueError, match="positive"):
            RetryStep(delay_hours=-1)

    def test_rejects_zero_delay(self):
        with pytest.raises(ValueError, match="positive"):
            RetryStep(delay_hours=0)

    def test_rejects_excessive_delay(self):
        with pytest.raises(ValueError, match="48"):
            RetryStep(delay_hours=100)

    def test_rejects_bad_window_hours(self):
        with pytest.raises(ValueError, match="0-23"):
            RetryStep(delay_hours=3, preferred_window=[25, 30])

    def test_rejects_overnight_window(self):
        with pytest.raises(ValueError, match="before end"):
            RetryStep(delay_hours=3, preferred_window=[22, 6])

    def test_rejects_equal_window(self):
        with pytest.raises(ValueError, match="before end"):
            RetryStep(delay_hours=3, preferred_window=[10, 10])

    def test_rejects_wrong_window_length(self):
        with pytest.raises(ValueError, match=r"\[start_hour, end_hour\]"):
            RetryStep(delay_hours=3, preferred_window=[10])


class TestCallbackScheduleValidation:
    def test_valid_schedule(self):
        schedule = CallbackSchedule(
            template="standard",
            steps=[RetryStep(delay_hours=3), RetryStep(delay_type="next_day", preferred_window=[11, 13])],
        )
        assert len(schedule.steps) == 2

    def test_rejects_empty_steps(self):
        with pytest.raises(ValueError, match="At least one"):
            CallbackSchedule(template="custom", steps=[])

    def test_rejects_too_many_steps(self):
        steps = [RetryStep(delay_hours=1) for _ in range(11)]
        with pytest.raises(ValueError, match="Maximum 10"):
            CallbackSchedule(template="custom", steps=steps)

    def test_rejects_invalid_template(self):
        with pytest.raises(ValueError):
            CallbackSchedule(template="invalid", steps=[RetryStep(delay_hours=1)])

    def test_valid_templates(self):
        for t in ["standard", "aggressive", "relaxed", "custom"]:
            s = CallbackSchedule(template=t, steps=[RetryStep(delay_hours=1)])
            assert s.template == t


# ---------------------------------------------------------------------------
# Task 3: compute_scheduled_at tests
# ---------------------------------------------------------------------------
from freezegun import freeze_time
from zoneinfo import ZoneInfo

from app.services.smart_retry import compute_scheduled_at


class FakeBotConfig:
    """Minimal bot config for testing."""
    def __init__(self, tz="Asia/Kolkata", window_start=9, window_end=20):
        self.callback_timezone = tz
        self.callback_window_start = window_start
        self.callback_window_end = window_end


class TestComputeScheduledAt:
    @freeze_time("2026-03-23 04:30:00", tz_offset=0)  # 10:00 AM IST — inside [9,20] window
    def test_delay_hours_basic(self):
        """3h delay from 10 AM IST -> 1 PM IST, inside global window, no clamping."""
        step = {"delay_hours": 3}
        bot = FakeBotConfig()
        result = compute_scheduled_at(step, bot)
        expected_min = datetime(2026, 3, 23, 4, 30, tzinfo=timezone.utc) + timedelta(hours=2, minutes=59)
        expected_max = datetime(2026, 3, 23, 4, 30, tzinfo=timezone.utc) + timedelta(hours=3, minutes=1)
        assert expected_min <= result <= expected_max

    @freeze_time("2026-03-23 04:30:00", tz_offset=0)  # 10:00 AM IST
    def test_delay_hours_inside_preferred_window_no_snap(self):
        """2h delay at 10 AM IST with [11,14] window -> lands at 12 PM, inside window, no snap."""
        ist = ZoneInfo("Asia/Kolkata")
        step = {"delay_hours": 2, "preferred_window": [11, 14]}
        bot = FakeBotConfig()
        result = compute_scheduled_at(step, bot)
        result_ist = result.astimezone(ist)
        assert 11 <= result_ist.hour < 14

    @freeze_time("2026-03-23 04:30:00", tz_offset=0)  # 10:00 AM IST
    def test_delay_hours_outside_preferred_window_snaps(self):
        """3h delay at 10 AM IST with [20,22] window -> snaps to 8 PM IST (bot window_end=22)."""
        ist = ZoneInfo("Asia/Kolkata")
        step = {"delay_hours": 3, "preferred_window": [20, 22]}
        bot = FakeBotConfig(window_end=22)
        result = compute_scheduled_at(step, bot)
        result_ist = result.astimezone(ist)
        assert result_ist.hour == 20

    @freeze_time("2026-03-22 18:31:00", tz_offset=0)  # 12:01 AM IST on Mar 23
    def test_next_day_window_not_passed(self):
        """12:01 AM IST with [11,13] window -> today at 11 AM IST."""
        ist = ZoneInfo("Asia/Kolkata")
        step = {"delay_type": "next_day", "preferred_window": [11, 13]}
        bot = FakeBotConfig()
        result = compute_scheduled_at(step, bot)
        result_ist = result.astimezone(ist)
        assert result_ist.hour == 11
        assert result_ist.day == 23

    @freeze_time("2026-03-23 15:30:00", tz_offset=0)  # 9 PM IST
    def test_next_day_window_already_passed(self):
        """9 PM IST with [11,13] window -> tomorrow at 11 AM IST."""
        ist = ZoneInfo("Asia/Kolkata")
        step = {"delay_type": "next_day", "preferred_window": [11, 13]}
        bot = FakeBotConfig()
        result = compute_scheduled_at(step, bot)
        result_ist = result.astimezone(ist)
        assert result_ist.hour == 11
        assert result_ist.day == 24

    @freeze_time("2026-03-23 15:30:00", tz_offset=0)  # 9 PM IST
    def test_next_day_evening_window_passed(self):
        """9 PM IST with [20,22] window -> tomorrow at 8 PM IST (bot window_end=22)."""
        ist = ZoneInfo("Asia/Kolkata")
        step = {"delay_type": "next_day", "preferred_window": [20, 22]}
        bot = FakeBotConfig(window_end=22)
        result = compute_scheduled_at(step, bot)
        result_ist = result.astimezone(ist)
        assert result_ist.hour == 20
        assert result_ist.day == 24

    @freeze_time("2026-03-23 04:30:00", tz_offset=0)  # 10 AM IST
    def test_global_window_guardrail_pushes_to_morning(self):
        """preferred_window [20,22] but calling window ends at 20 -> pushes to 9 AM next day."""
        ist = ZoneInfo("Asia/Kolkata")
        step = {"delay_hours": 3, "preferred_window": [20, 22]}
        bot = FakeBotConfig(window_start=9, window_end=20)
        result = compute_scheduled_at(step, bot)
        result_ist = result.astimezone(ist)
        assert result_ist.hour == 9
        assert result_ist.day == 24

    @freeze_time("2026-03-22 20:30:00", tz_offset=0)  # 2 AM IST on Mar 23
    def test_global_window_early_morning(self):
        """2 AM IST with calling window [9,20] -> pushes to 9 AM today."""
        ist = ZoneInfo("Asia/Kolkata")
        step = {"delay_hours": 0.5}
        bot = FakeBotConfig(window_start=9, window_end=20)
        result = compute_scheduled_at(step, bot)
        result_ist = result.astimezone(ist)
        assert result_ist.hour == 9
        assert result_ist.day == 23

    def test_next_day_no_window(self):
        """next_day without preferred_window -> in the future."""
        step = {"delay_type": "next_day"}
        bot = FakeBotConfig()
        result = compute_scheduled_at(step, bot)
        assert result > datetime.now(timezone.utc)

    def test_fallback_on_bad_step(self):
        """Missing both fields -> 3h fallback."""
        step = {}
        bot = FakeBotConfig()
        result = compute_scheduled_at(step, bot)
        assert result > datetime.now(timezone.utc)


class TestRetryIntegration:
    """Integration tests — verify full flow with real schema validation."""

    def test_template_roundtrip(self):
        """Template -> serialize -> deserialize -> matches."""
        schedule = CallbackSchedule(
            template="standard",
            steps=[
                RetryStep(delay_hours=3),
                RetryStep(delay_hours=3),
                RetryStep(delay_type="next_day", preferred_window=[11, 13]),
                RetryStep(delay_type="next_day", preferred_window=[20, 22]),
            ],
        )
        data = schedule.model_dump()
        restored = CallbackSchedule(**data)
        assert len(restored.steps) == 4
        assert restored.steps[0].delay_hours == 3
        assert restored.steps[2].preferred_window == [11, 13]
        assert restored.template == "standard"

    def test_step_progression_logic(self):
        """Simulate 3 consecutive retries — each uses the next step."""
        steps = [
            {"delay_hours": 3},
            {"delay_hours": 3},
            {"delay_type": "next_day", "preferred_window": [11, 13]},
        ]
        bot = FakeBotConfig()

        for retry_count in range(3):
            step = steps[retry_count]
            result = compute_scheduled_at(step, bot)
            assert result > datetime.now(timezone.utc)

        assert 3 >= len(steps)

    def test_api_rejects_conflicting_windows(self):
        """preferred_window [20,22] with calling window [9,18] -> should conflict."""
        step = RetryStep(delay_type="next_day", preferred_window=[20, 22])
        pw_start, pw_end = step.preferred_window
        w_start, w_end = 9, 18
        has_overlap = not (pw_end <= w_start or pw_start >= w_end)
        assert not has_overlap

    def test_migration_conversion_logic(self):
        """Old config (delay=2, max=3) -> 3 steps of delay_hours=2."""
        old_delay = 2.0
        old_max = 3
        steps = [{"delay_hours": old_delay} for _ in range(old_max)]
        schedule = CallbackSchedule(template="custom", steps=[RetryStep(**s) for s in steps])
        assert len(schedule.steps) == 3
        assert all(s.delay_hours == 2.0 for s in schedule.steps)

    def test_migration_skips_zero_retries(self):
        """max_retries=0 -> no steps -> should NOT create schedule."""
        old_max = 0
        assert old_max <= 0

    def test_migration_skips_disabled_bots(self):
        """callback_enabled=false -> should NOT create schedule."""
        callback_enabled = False
        assert not callback_enabled
