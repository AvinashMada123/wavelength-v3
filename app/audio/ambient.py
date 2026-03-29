"""Singleton WAV loader for ambient sound presets.

Loads WAV files once at app startup into shared read-only numpy arrays.
Zero per-call I/O. If any preset fails to load, it is skipped (never crashes).
"""

import hashlib
import wave
from pathlib import Path
from typing import Optional

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

EXPECTED_SAMPLE_RATE = 16000
EXPECTED_CHANNELS = 1
EXPECTED_SAMPLE_WIDTH = 2  # 16-bit PCM

# SHA-256 checksums of known-good WAV files (prevents silent corruption)
CHECKSUMS: dict[str, str] = {
    "static": "b612c336ca3cf99904e04cbba60ffe8162754f696958dcfcdf697ce710bee424",
    "office_hum": "b3675d580f62f9e2a606b43407191f6e3b6a192be12f2e7d0c6280cf7b296ae7",
}

# Module-level singleton: preset_name -> numpy int16 array
_presets: dict[str, np.ndarray] = {}
_loaded: bool = False

# Default presets directory (relative to project root)
_DEFAULT_PRESETS_DIR = Path(__file__).parent / "presets"


def load_presets(presets_dir: Path | str | None = None) -> None:
    """Load all WAV presets from disk into memory.

    Call once at app startup. On ANY failure per file: logs CRITICAL,
    skips that preset, continues. Never raises.
    """
    global _loaded
    directory = Path(presets_dir) if presets_dir else _DEFAULT_PRESETS_DIR

    if not directory.is_dir():
        logger.critical("ambient_presets_dir_missing", path=str(directory))
        return

    loaded_count = 0
    for wav_path in sorted(directory.glob("*.wav")):
        preset_name = wav_path.stem
        expected_checksum = CHECKSUMS.get(preset_name)

        samples = _validate_and_load(wav_path, expected_checksum)
        if samples is not None:
            _presets[preset_name] = samples
            loaded_count += 1
            logger.info(
                "ambient_preset_loaded",
                preset=preset_name,
                samples=len(samples),
                duration_s=round(len(samples) / EXPECTED_SAMPLE_RATE, 1),
            )

    _loaded = loaded_count > 0
    logger.info("ambient_presets_ready", loaded=loaded_count, available=list(_presets.keys()))


def _validate_and_load(path: Path, expected_checksum: str | None) -> Optional[np.ndarray]:
    """Validate WAV format + checksum, return int16 numpy array or None."""
    try:
        # Checksum verification
        if expected_checksum:
            file_bytes = path.read_bytes()
            actual = hashlib.sha256(file_bytes).hexdigest()
            if actual != expected_checksum:
                logger.critical(
                    "ambient_checksum_mismatch",
                    path=str(path),
                    expected=expected_checksum[:16],
                    actual=actual[:16],
                )
                return None

        # WAV format validation
        with wave.open(str(path), "rb") as wf:
            if wf.getnchannels() != EXPECTED_CHANNELS:
                logger.critical(
                    "ambient_wrong_channels",
                    path=str(path),
                    channels=wf.getnchannels(),
                    expected=EXPECTED_CHANNELS,
                )
                return None

            if wf.getsampwidth() != EXPECTED_SAMPLE_WIDTH:
                logger.critical(
                    "ambient_wrong_sample_width",
                    path=str(path),
                    sample_width=wf.getsampwidth(),
                    expected=EXPECTED_SAMPLE_WIDTH,
                )
                return None

            if wf.getframerate() != EXPECTED_SAMPLE_RATE:
                logger.critical(
                    "ambient_wrong_sample_rate",
                    path=str(path),
                    sample_rate=wf.getframerate(),
                    expected=EXPECTED_SAMPLE_RATE,
                )
                return None

            raw = wf.readframes(wf.getnframes())

        samples = np.frombuffer(raw, dtype=np.int16)
        if len(samples) == 0:
            logger.critical("ambient_empty_wav", path=str(path))
            return None

        # Make read-only to prevent accidental mutation across calls
        samples.flags.writeable = False
        return samples

    except Exception:
        logger.critical("ambient_load_failed", path=str(path), exc_info=True)
        return None


def get_preset(name: str) -> Optional[np.ndarray]:
    """Return the loaded numpy buffer for a preset, or None if not found."""
    return _presets.get(name)


def is_loaded() -> bool:
    """True if at least one preset loaded successfully."""
    return _loaded


def get_available_presets() -> list[str]:
    """Return names of all loaded presets."""
    return list(_presets.keys())


def _reset_for_testing() -> None:
    """Reset module state — only for use in tests."""
    global _loaded
    _presets.clear()
    _loaded = False
