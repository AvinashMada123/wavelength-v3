"""Tests for Deepgram keyword boosting and entity hint generation.

Tests the pure functions extracted from factory.py:
- build_deepgram_keywords(): extracts keywords from bot config
- build_entity_hint_suffix(): builds system prompt entity hints
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

# structlog needs SimpleNamespace, not MagicMock
sys.modules.setdefault(
    "structlog", SimpleNamespace(get_logger=lambda *a, **kw: MagicMock())
)

# Brute-force: scan factory.py and ALL transitive app imports for every
# external module reference, then pre-populate sys.modules.
# Using a recursive approach to catch everything.
import importlib
import pathlib

_PROJECT = pathlib.Path(__file__).resolve().parent.parent
_EXT_PREFIXES = ("pipecat", "deepgram", "aiohttp", "starlette")


def _collect_external_imports(source_dir: pathlib.Path) -> set[str]:
    """Scan .py files under source_dir for 'from X import' and 'import X' of external packages."""
    result = set()
    for py_file in source_dir.rglob("*.py"):
        try:
            text = py_file.read_text()
        except Exception:
            continue
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("#"):
                continue
            for prefix in _EXT_PREFIXES:
                if f"from {prefix}" in line or f"import {prefix}" in line:
                    # Extract the full dotted module path
                    if line.startswith("from "):
                        mod = line.split("from ", 1)[1].split(" import")[0].strip()
                    else:
                        mod = line.split("import ", 1)[1].split(" ")[0].split(",")[0].strip()
                    # Add the module AND all parent paths
                    parts = mod.split(".")
                    for i in range(1, len(parts) + 1):
                        result.add(".".join(parts[:i]))
    return result


_all_externals = _collect_external_imports(_PROJECT / "app")
for mod_name in sorted(_all_externals):
    sys.modules.setdefault(mod_name, MagicMock())

# Also mock aiohttp and starlette roots if not caught
for m in ["aiohttp", "starlette", "starlette.websockets"]:
    sys.modules.setdefault(m, MagicMock())

# Fix specific attrs that factory.py reads at import time
sys.modules["pipecat.transports.base_output"].BOT_VAD_STOP_SECS = 0.35
_dg = sys.modules["deepgram"]
_dg.LiveOptions = lambda **kw: SimpleNamespace(**kw)

import pytest

from app.pipeline.factory import build_deepgram_keywords, build_entity_hint_suffix


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bot(**overrides) -> SimpleNamespace:
    defaults = {
        "agent_name": "Sneha",
        "company_name": "Freedom with AI",
        "event_name": "AI Masterclass",
        "context_variables": {},
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ===========================================================================
# build_deepgram_keywords
# ===========================================================================

class TestBuildDeepgramKeywords:

    def test_basic_fields(self):
        bot = _make_bot()
        kw = build_deepgram_keywords(bot)
        # Should contain agent name, company name, event name with boosts
        assert "Sneha:5" in kw
        assert "Freedom with AI:5" in kw
        assert "Freedom:3" in kw
        assert "with:3" in kw  # len("with") > 2
        assert "AI Masterclass:4" in kw
        assert "Masterclass:2" in kw

    def test_short_word_parts_excluded(self):
        bot = _make_bot(agent_name="Dr AI")
        kw = build_deepgram_keywords(bot)
        # "AI" is only 2 chars — should NOT be added as a separate part
        assert "AI:3" not in kw
        # But the full name should be there
        assert "Dr AI:5" in kw

    def test_custom_keywords_from_context_variables(self):
        bot = _make_bot(context_variables={"stt_keywords": ["Sourabh", "Avinash:5"]})
        kw = build_deepgram_keywords(bot)
        assert "Sourabh:3" in kw  # Default boost applied
        assert "Avinash:5" in kw  # Custom boost preserved

    def test_deduplication(self):
        bot = _make_bot(
            agent_name="Sneha",
            context_variables={"stt_keywords": ["Sneha:3"]},
        )
        kw = build_deepgram_keywords(bot)
        # "Sneha:5" from agent_name and "Sneha:3" from stt_keywords
        # Should keep only the first one (case-insensitive dedup)
        sneha_entries = [k for k in kw if k.lower().startswith("sneha:")]
        assert len(sneha_entries) == 1
        assert sneha_entries[0] == "Sneha:5"  # First one wins

    def test_empty_bot(self):
        bot = _make_bot(agent_name="", company_name="", event_name=None, context_variables={})
        kw = build_deepgram_keywords(bot)
        assert kw == []

    def test_no_event_name(self):
        bot = _make_bot(event_name=None)
        kw = build_deepgram_keywords(bot)
        assert not any("Masterclass" in k for k in kw)
        # agent_name and company_name should still be present
        assert "Sneha:5" in kw

    def test_invalid_stt_keywords_ignored(self):
        bot = _make_bot(context_variables={"stt_keywords": [123, None, "", "  ", "Valid"]})
        kw = build_deepgram_keywords(bot)
        # Only "Valid" should be added
        assert "Valid:3" in kw
        # Empty/whitespace/non-string should be skipped
        assert len([k for k in kw if "123" in k]) == 0

    def test_stt_keywords_not_list(self):
        bot = _make_bot(context_variables={"stt_keywords": "not a list"})
        kw = build_deepgram_keywords(bot)
        # Should not crash, just ignore
        assert "Sneha:5" in kw  # Other keywords still work

    def test_no_context_variables(self):
        bot = _make_bot(context_variables=None)
        kw = build_deepgram_keywords(bot)
        assert "Sneha:5" in kw  # Should not crash

    def test_missing_context_variables_attr(self):
        bot = SimpleNamespace(agent_name="Test", company_name="Co")
        # No context_variables, no event_name at all
        kw = build_deepgram_keywords(bot)
        assert "Test:5" in kw
        assert "Co:5" in kw


# ===========================================================================
# build_entity_hint_suffix
# ===========================================================================

class TestBuildEntityHintSuffix:

    def test_basic_hints(self):
        bot = _make_bot()
        suffix = build_entity_hint_suffix(bot)
        assert "Your name is Sneha" in suffix
        assert "Company: Freedom with AI" in suffix
        assert "Event: AI Masterclass" in suffix
        assert "speech recognition" in suffix  # The framing text

    def test_empty_bot_returns_empty(self):
        bot = _make_bot(agent_name="", company_name="", event_name=None)
        suffix = build_entity_hint_suffix(bot)
        assert suffix == ""

    def test_custom_keywords_included(self):
        bot = _make_bot(context_variables={"stt_keywords": ["Sourabh:5", "Treasury"]})
        suffix = build_entity_hint_suffix(bot)
        assert "Key terms: Sourabh, Treasury" in suffix

    def test_boost_values_stripped_from_hints(self):
        bot = _make_bot(context_variables={"stt_keywords": ["Avinash:5"]})
        suffix = build_entity_hint_suffix(bot)
        # Should show "Avinash" not "Avinash:5"
        assert "Avinash" in suffix
        assert ":5" not in suffix

    def test_no_event(self):
        bot = _make_bot(event_name=None)
        suffix = build_entity_hint_suffix(bot)
        assert "Event:" not in suffix
        assert "Your name is Sneha" in suffix  # Other hints still present

    def test_suffix_starts_with_newlines(self):
        bot = _make_bot()
        suffix = build_entity_hint_suffix(bot)
        assert suffix.startswith("\n\n")

    def test_no_context_variables(self):
        bot = _make_bot(context_variables=None)
        suffix = build_entity_hint_suffix(bot)
        assert "Your name is Sneha" in suffix  # Should not crash
        assert "Key terms" not in suffix
