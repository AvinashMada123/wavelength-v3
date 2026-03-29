"""AmbientSoundMixer — mixes looping background noise into TTS audio frames.

Phase 0: Speech-only mixing. Only processes TTSAudioRawFrame.
Silence gaps between utterances get no noise injection.

The mixer reads from a shared read-only numpy buffer (loaded at app startup)
and maintains a per-instance loop position so concurrent calls don't interfere.
"""

import numpy as np
import structlog
from pipecat.frames.frames import EndFrame, StartFrame, TTSAudioRawFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from app.audio.ambient import get_preset

logger = structlog.get_logger(__name__)

# Hard cap — never exceed regardless of config
MAX_VOLUME = 0.3


class AmbientSoundMixer(FrameProcessor):
    """Mix looping ambient noise into TTS audio frames.

    Each call instance gets its own loop position cursor into the shared
    preset buffer. The buffer is read-only; no mutation occurs.
    """

    def __init__(
        self,
        preset: str,
        volume: float = 0.08,
        call_sid: str = "",
        **kwargs,
    ):
        super().__init__(name="AmbientSoundMixer", **kwargs)
        self._call_sid = call_sid
        self._volume = min(max(volume, 0.0), MAX_VOLUME)
        self._preset_name = preset
        self._buffer: np.ndarray | None = get_preset(preset)
        self._loop_pos: int = 0
        self._frames_mixed: int = 0
        self._active = self._buffer is not None

        if not self._active:
            logger.warning(
                "ambient_mixer_disabled",
                call_sid=call_sid,
                preset=preset,
                reason="preset_not_loaded",
            )
        else:
            logger.info(
                "ambient_mixer_init",
                call_sid=call_sid,
                preset=preset,
                volume=self._volume,
                buffer_samples=len(self._buffer),
            )

    async def process_frame(self, frame, direction: FrameDirection):
        """Process a pipeline frame. Mix noise into TTS audio; pass all else through."""
        # StartFrame: required by Pipecat lifecycle
        if isinstance(frame, StartFrame):
            await self.push_frame(frame, direction)
            return

        # Only mix into TTS audio frames when active
        if isinstance(frame, TTSAudioRawFrame) and self._active:
            try:
                mixed_audio = self._mix(frame.audio)
                frame.audio = mixed_audio
                self._frames_mixed += 1
            except Exception:
                logger.exception(
                    "ambient_mixer_error",
                    call_sid=self._call_sid,
                    preset=self._preset_name,
                )
                # Fallback: frame.audio is untouched — push as-is
            await self.push_frame(frame, direction)
            return

        # EndFrame: log summary before passing through
        if isinstance(frame, EndFrame) and self._frames_mixed > 0:
            logger.info(
                "ambient_mixer_summary",
                call_sid=self._call_sid,
                preset=self._preset_name,
                frames_mixed=self._frames_mixed,
                volume=self._volume,
            )

        await self.push_frame(frame, direction)

    def _mix(self, pcm_bytes: bytes) -> bytes:
        """Mix ambient noise into PCM bytes. Returns new PCM bytes."""
        n_samples = len(pcm_bytes) // 2
        if n_samples == 0:
            return pcm_bytes

        speech = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
        noise = self._get_noise_segment(n_samples)

        mixed = speech + noise * self._volume
        return np.clip(mixed, -32768, 32767).astype(np.int16).tobytes()

    def _get_noise_segment(self, n_samples: int) -> np.ndarray:
        """Extract n_samples from the looping preset buffer as float32."""
        buf = self._buffer
        buf_len = len(buf)
        result = np.empty(n_samples, dtype=np.float32)

        written = 0
        while written < n_samples:
            remaining = n_samples - written
            available = buf_len - self._loop_pos
            chunk = min(remaining, available)
            result[written : written + chunk] = buf[
                self._loop_pos : self._loop_pos + chunk
            ].astype(np.float32)
            self._loop_pos = (self._loop_pos + chunk) % buf_len
            written += chunk

        return result
