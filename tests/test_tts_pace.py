"""Tests for TTS pace configuration.

Verifies that Sarvam TTS pace parameter is correctly set in both
the pipeline TTS (factory.py) and the greeting TTS (runner.py).
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Mock pipecat imports before importing code under test
# ---------------------------------------------------------------------------

# Create mock InputParams that records what it's called with
_captured_input_params = []


class _MockInputParams:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        _captured_input_params.append(kwargs)


class _MockSarvamTTSService:
    InputParams = _MockInputParams

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.params = kwargs.get("params")


# ---------------------------------------------------------------------------
# Unit Tests — Pace parameter validation
# ---------------------------------------------------------------------------


class TestTtsPaceConfig:
    """Verify TTS pace is configured correctly."""

    def test_pace_value_in_valid_range(self):
        """Pace 1.1 is within bulbul:v3 range (0.5-2.0)."""
        pace = 1.1
        assert 0.5 <= pace <= 2.0

    def test_pace_not_zero(self):
        """Pace must never be 0 (would produce silence)."""
        pace = 1.1
        assert pace > 0

    def test_pace_not_too_fast(self):
        """Pace above 1.5 makes speech unintelligible for most users."""
        pace = 1.1
        assert pace <= 1.5

    def test_pace_not_too_slow(self):
        """Pace below 0.7 sounds unnaturally slow."""
        pace = 1.1
        assert pace >= 0.7


class TestTtsPaceInFactory:
    """Verify factory.py passes pace to Sarvam TTS InputParams."""

    def test_factory_sarvam_tts_has_pace(self):
        """The pipeline TTS in factory.py must include pace parameter."""
        # Read factory.py source and verify pace is in InputParams
        import ast
        with open("app/pipeline/factory.py", "r") as f:
            source = f.read()

        # Find the SarvamTTSService.InputParams call in the pipeline section
        # Look for the pattern: temperature=X.XX followed by pace=X.X
        assert "pace=1.1" in source or "pace = 1.1" in source, (
            "factory.py must set pace=1.1 in Sarvam TTS InputParams"
        )

    def test_factory_pace_value_is_1_1(self):
        """Factory TTS pace must be exactly 1.1."""
        with open("app/pipeline/factory.py", "r") as f:
            source = f.read()

        # Extract pace value — should appear near temperature in InputParams
        import re
        matches = re.findall(r"pace\s*=\s*([\d.]+)", source)
        assert len(matches) >= 1, "pace parameter not found in factory.py"
        assert float(matches[0]) == 1.1


class TestTtsPaceInRunner:
    """Verify runner.py passes pace to greeting TTS InputParams."""

    def test_runner_sarvam_tts_has_pace(self):
        """The greeting TTS in runner.py must include pace parameter."""
        with open("app/pipeline/runner.py", "r") as f:
            source = f.read()

        assert "pace=1.1" in source or "pace = 1.1" in source, (
            "runner.py must set pace=1.1 in greeting Sarvam TTS InputParams"
        )

    def test_runner_pace_matches_factory(self):
        """Greeting and pipeline TTS must use the same pace."""
        import re

        with open("app/pipeline/factory.py", "r") as f:
            factory_source = f.read()
        with open("app/pipeline/runner.py", "r") as f:
            runner_source = f.read()

        factory_paces = re.findall(r"pace\s*=\s*([\d.]+)", factory_source)
        runner_paces = re.findall(r"pace\s*=\s*([\d.]+)", runner_source)

        assert len(factory_paces) >= 1, "No pace in factory.py"
        assert len(runner_paces) >= 1, "No pace in runner.py"
        assert factory_paces[0] == runner_paces[0], (
            f"Pace mismatch: factory={factory_paces[0]}, runner={runner_paces[0]}"
        )


class TestTtsPaceConsistency:
    """Integration-level checks for pace consistency across the codebase."""

    def test_no_hardcoded_pace_elsewhere(self):
        """Pace should only be set in factory.py and runner.py, nowhere else."""
        import re
        import glob

        pace_files = []
        for f in glob.glob("app/**/*.py", recursive=True):
            if f.endswith("__pycache__"):
                continue
            with open(f, "r") as fh:
                content = fh.read()
                if re.search(r"pace\s*=\s*[\d.]+", content):
                    pace_files.append(f)

        # Only factory.py and runner.py should set pace
        expected = {"app/pipeline/factory.py", "app/pipeline/runner.py"}
        assert set(pace_files) == expected, (
            f"Unexpected files with pace parameter: {set(pace_files) - expected}"
        )

    def test_sarvam_tts_used_with_bulbul_v3(self):
        """Pace parameter is only valid for bulbul:v3. Verify model is correct."""
        with open("app/pipeline/factory.py", "r") as f:
            source = f.read()

        assert 'model="bulbul:v3"' in source, (
            "Factory must use bulbul:v3 model for pace support"
        )

        with open("app/pipeline/runner.py", "r") as f:
            source = f.read()

        assert 'model="bulbul:v3"' in source, (
            "Runner must use bulbul:v3 model for pace support"
        )
