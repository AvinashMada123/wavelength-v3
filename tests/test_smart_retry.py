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
