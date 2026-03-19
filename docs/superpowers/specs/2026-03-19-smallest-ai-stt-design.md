# Smallest AI Pulse STT Integration — Design Spec

## Overview

Add Smallest AI's Pulse STT as a speech-to-text provider option in Wavelength. Custom Pipecat STTService implementation using WebSocket streaming. Available only to super_admin accounts initially.

## Technical Details

### Pulse STT API

- **WebSocket endpoint:** `wss://waves-api.smallest.ai/api/v1/pulse/get_text`
- **Auth:** `Authorization: Bearer <API_KEY>` header on connect
- **Query params:** `model=pulse`, `language=en` (or `multi`), `sample_rate=16000`
- **Audio input:** Raw PCM bytes sent as binary WebSocket frames (100ms chunks)
- **Response format:** JSON with `text` (transcript), `is_final` (bool), optional `words` array
- **Latency:** ~64ms time-to-first-transcript
- **Supported formats:** Linear16 PCM at 16kHz (matches Plivo/Twilio audio format exactly — no conversion needed)

### Implementation Pattern

Follow Sarvam STT's pattern but simpler since we use raw WebSocket (no SDK):

1. **Extends `STTService`** (not `WebsocketSTTService`) — manages WebSocket manually
2. **`_connect()`** — opens `websockets` connection with auth header + query params
3. **`run_stt(audio)`** — sends raw PCM bytes as binary WebSocket frame, yields None (transcripts come via receive task)
4. **`_receive_task_handler()`** — background task reading JSON messages, pushing `TranscriptionFrame` for final transcripts and `InterimTranscriptionFrame` for partials
5. **Keepalive** — sends silent PCM every 5s to prevent connection drop

### Files

| File | Action | Change |
|------|--------|--------|
| `app/services/smallest_stt.py` | Create | Custom Pipecat STTService for Pulse |
| `app/config.py` | Modify | Add `SMALLEST_API_KEY: str = ""` |
| `app/pipeline/factory.py` | Modify | Add `smallest` branch in STT provider selection |
| `frontend/src/lib/constants.ts` | Modify | Add `smallest` to `STT_PROVIDER_OPTIONS` (admin only) |

### No migration needed — `stt_provider` is already a free-text field.
