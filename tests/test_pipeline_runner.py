"""Unit tests for pipeline/runner.py — _resolve_greeting_text (pure function)."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.modules.setdefault(
    "structlog", SimpleNamespace(get_logger=lambda *a, **kw: MagicMock())
)

# Mock heavy pipecat imports that _resolve_greeting_text doesn't need
for mod in [
    "pipecat", "pipecat.frames", "pipecat.frames.frames",
    "pipecat.pipeline", "pipecat.pipeline.runner",
    "pipecat.transcriptions", "pipecat.transcriptions.language",
    "pipecat.services", "pipecat.services.google",
    "pipecat.services.google.tts", "pipecat.services.sarvam",
    "pipecat.services.sarvam.tts", "pipecat.services.elevenlabs",
    "pipecat.services.elevenlabs.tts",
    "aiohttp",
    "starlette", "starlette.websockets",
]:
    sys.modules.setdefault(mod, MagicMock())

# Mock app.config.settings and gemini_key_pool
sys.modules.setdefault(
    "app.config",
    SimpleNamespace(
        settings=SimpleNamespace(
            GREETING_DIRECT_PLAY=False,
            COMFORT_NOISE_ENABLED=False,
            SARVAM_API_KEY="fake",
            ELEVENLABS_API_KEY="fake",
            GOOGLE_CLOUD_PROJECT="fake",
            VERTEX_AI_LOCATION="us-central1",
        ),
        gemini_key_pool=SimpleNamespace(get_key=lambda: "fake-key"),
    ),
)

# Mock pipeline factory and serializer
sys.modules.setdefault("app.pipeline.factory", MagicMock())
sys.modules.setdefault("app.serializers.plivo_pcm", SimpleNamespace(
    PLIVO_SAMPLE_RATE=16000,
    ComfortNoiseInjector=MagicMock(),
))
sys.modules.setdefault("app.models.bot_config", MagicMock())
sys.modules.setdefault("app.models.schemas", MagicMock())

from app.pipeline.runner import _resolve_greeting_text


def _make_ctx(**overrides):
    defaults = {
        "call_sid": "test-sid",
        "contact_name": "Rahul",
        "filled_prompt": "Some prompt text",
        "tts_voice": "test-voice",
        "language": "en-IN",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_bot(**overrides):
    defaults = {
        "agent_name": "Ava",
        "company_name": "Wavelength",
        "greeting_template": None,
        "callback_greeting_template": None,
        "event_name": "AI Workshop",
        "event_date": "March 25",
        "event_time": "7 PM",
        "location": "Mumbai",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# _resolve_greeting_text
# ---------------------------------------------------------------------------

class TestResolveGreetingText:
    def test_default_greeting(self):
        ctx = _make_ctx()
        bot = _make_bot()
        result = _resolve_greeting_text(ctx, bot)
        assert "Rahul" in result
        assert "Ava" in result
        assert "Wavelength" in result

    def test_custom_greeting_template(self):
        ctx = _make_ctx()
        bot = _make_bot(greeting_template="Hey {contact_name}! {agent_name} here from {company_name}.")
        result = _resolve_greeting_text(ctx, bot)
        assert result == "Hey Rahul! Ava here from Wavelength."

    def test_callback_greeting_for_returning_caller(self):
        ctx = _make_ctx(filled_prompt="blah PREVIOUS CALL HISTORY WITH THIS CONTACT blah")
        bot = _make_bot(
            callback_greeting_template="Hey {contact_name}, {agent_name} calling back!",
        )
        result = _resolve_greeting_text(ctx, bot)
        assert "calling back" in result
        assert "Rahul" in result

    def test_non_returning_caller_ignores_callback_template(self):
        ctx = _make_ctx(filled_prompt="Some normal prompt")
        bot = _make_bot(
            greeting_template="Normal greeting {contact_name}",
            callback_greeting_template="Callback greeting {contact_name}",
        )
        result = _resolve_greeting_text(ctx, bot)
        assert "Normal greeting" in result
        assert "Callback" not in result

    def test_null_contact_name_uses_there(self):
        ctx = _make_ctx(contact_name=None)
        bot = _make_bot()
        result = _resolve_greeting_text(ctx, bot)
        assert "there" in result

    def test_event_variables_in_template(self):
        ctx = _make_ctx()
        bot = _make_bot(
            greeting_template="Join {event_name} on {event_date} at {event_time} in {location}",
        )
        result = _resolve_greeting_text(ctx, bot)
        assert "AI Workshop" in result
        assert "March 25" in result
        assert "7 PM" in result
        assert "Mumbai" in result

    def test_missing_template_var_replaced_with_empty(self):
        ctx = _make_ctx()
        bot = _make_bot(greeting_template="Hello {contact_name}, your {unknown_var} is ready")
        result = _resolve_greeting_text(ctx, bot)
        assert "Hello Rahul" in result
        assert "unknown_var" not in result  # replaced with empty string

    def test_empty_greeting_falls_back_to_default(self):
        ctx = _make_ctx()
        bot = _make_bot(greeting_template="   ")
        result = _resolve_greeting_text(ctx, bot)
        # Should fall back to _DEFAULT_GREETING
        assert "Rahul" in result
        assert "Ava" in result

    def test_none_event_fields_become_empty(self):
        ctx = _make_ctx()
        bot = _make_bot(
            greeting_template="{event_name} on {event_date}",
            event_name=None,
            event_date=None,
        )
        result = _resolve_greeting_text(ctx, bot)
        assert result.strip() == "on"

    def test_filled_prompt_none(self):
        ctx = _make_ctx(filled_prompt=None)
        bot = _make_bot()
        result = _resolve_greeting_text(ctx, bot)
        # Should not crash, just use normal greeting
        assert "Rahul" in result

    def test_none_agent_name(self):
        ctx = _make_ctx()
        bot = _make_bot(agent_name=None)
        result = _resolve_greeting_text(ctx, bot)
        # Should not crash
        assert isinstance(result, str)

    def test_none_company_name(self):
        ctx = _make_ctx()
        bot = _make_bot(company_name=None)
        result = _resolve_greeting_text(ctx, bot)
        # Should not crash
        assert isinstance(result, str)
