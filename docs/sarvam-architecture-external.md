# Wavelength — Sarvam Integration Architecture
**Prepared for:** Sarvam Engineering Team
**Date:** March 19, 2026

---

## 1. Platform Overview

Wavelength is a real-time AI voice calling platform. We use Sarvam for both speech-to-text (STT) and text-to-speech (TTS) in our voice pipeline.

- **Framework:** Pipecat 0.0.104 (open-source voice AI framework)
- **Telephony:** Plivo (WebSocket-based audio streaming)
- **Deployment:** GCP VM in `asia-south1` (Mumbai)
- **Scale:** ~100 concurrent calls target

---

## 2. Audio Format

All audio flows as:
- **Format:** PCM 16-bit signed little-endian
- **Sample rate:** 16,000 Hz
- **Channels:** Mono
- **Chunk size:** 640 bytes per frame (20ms at 16kHz)

This is the standard format from Plivo's WebSocket stream. Audio is sent to Sarvam STT and received from Sarvam TTS in this format.

---

## 3. Sarvam STT Integration (saaras:v3)

### Connection
- **Transport:** WebSocket via Pipecat's built-in `SarvamSTTService`
- **Model:** `saaras:v3`
- **Audio input:** Raw PCM 16kHz (base64-encoded per Sarvam SDK)

### Configuration
```
model: saaras:v3
sample_rate: 16000
input_audio_codec: wav
vad_signals: True
high_vad_sensitivity: True
keepalive_timeout: 30s
keepalive_interval: 5s
```

### Language Settings
We configure language per-bot. Common settings:
- `en-IN` — English (India) — most common
- `unknown` — Auto-detect (maps to Sarvam's auto-detect mode)
- `ta-IN`, `te-IN`, `hi-IN` — Regional languages when known

### How We Process STT Events

1. **START_SPEECH** → We note that the user started speaking
2. **Audio flows continuously** → PCM chunks sent as base64 via WebSocket
3. **END_SPEECH** → We expect a transcript to follow
4. **Transcript received** → Text is passed to our LLM for response generation

**Key behavior:** When END_SPEECH fires, we wait up to 2 seconds for the transcript. If no transcript arrives within 2 seconds, we log a timeout and send a stop frame.

### Observed STT Issues (Detail in Audit Report)

| Issue | Frequency | Impact |
|-------|-----------|--------|
| END_SPEECH with no transcript | 31 events / 6 calls | Bot goes silent, user confused |
| Repetition hallucination (126x loop) | 1 call observed | Conversation destroyed |
| Speech fragmentation (continuous speech split into 3-5 segments) | Every call > 60s | LLM misinterprets fragments |
| Language misidentification (English → Hindi/Bengali) | On auto-detect mode | Call terminated incorrectly |
| Phantom word hallucination ("Thank you", "Bye") | Multiple calls | Premature call ending |
| Garbled Tamil transcription | Multiple calls | User frustration |

---

## 4. Sarvam TTS Integration (bulbul:v3)

### Connection
- **Transport:** WebSocket via Pipecat's built-in `SarvamTTSService`
- **Model:** `bulbul:v3`
- **Audio output:** PCM 16kHz

### Configuration
```
model: bulbul:v3
sample_rate: 16000
min_buffer_size: 30
max_chunk_length: 100
temperature: 0.7
output_audio_codec: linear16
```

### How We Send Text to TTS

We don't send the full LLM response at once. Text is split into phrase-level chunks before being sent to TTS:

- **First phrase:** ~30 characters (sent quickly for low time-to-first-audio)
- **Subsequent phrases:** ~50 characters (larger chunks for fewer gaps)
- **Split points:** Sentence endings (`.!?`) and phrase delimiters (`,;:`)

Each chunk is sent as a separate text message on the WebSocket. Sarvam synthesizes and streams audio back for each chunk.

### Observed TTS Issues (Detail in Audit Report)

| Issue | Frequency | Impact |
|-------|-----------|--------|
| Inter-phrase audio gaps (silence between chunks) | Every call | 23-71% of call is silence |
| TTS stall (14.1 seconds of no audio) | 1 call observed | Caller thinks connection dropped |
| First-phrase latency (700-3800ms) | Every call | Noticeable delay before bot speaks |
| Volume inconsistency across calls | Across all calls | Some calls very quiet, some clip |

---

## 5. Call Flow Diagram

```
Phone User
    │
    ▼
Plivo (Telephony)
    │ WebSocket: PCM 16kHz
    ▼
┌─────────────────────────────────┐
│        Wavelength Server        │
│                                 │
│  Audio In ──► Sarvam STT        │
│                  │              │
│              Transcript         │
│                  │              │
│              LLM (generates     │
│              response text)     │
│                  │              │
│              Text chunks        │
│                  │              │
│              Sarvam TTS         │
│                  │              │
│  Audio Out ◄── PCM audio        │
│                                 │
└─────────────────────────────────┘
    │ WebSocket: PCM 16kHz
    ▼
Plivo (Telephony)
    │
    ▼
Phone User
```

---

## 6. Latency Profile from Our Server

Measured from GCP `asia-south1-c` (Mumbai):

| Endpoint | TCP Connect | Ping RTT |
|----------|------------|----------|
| api.sarvam.ai | 6.8ms | 4.3ms |
| Plivo Media WS | 247ms | N/A |

Sarvam connectivity is excellent from our server. The latency issues we observe are in synthesis/transcription time, not network.

---

## 7. Reproduction Steps

To reproduce the issues documented in our audit report:

1. **Repetition hallucination:** Make a call where the user gives a short Tamil acknowledgment ("sari" / "ok"). The STT may enter a repetition loop.

2. **END_SPEECH timeout:** Make calls > 60 seconds with natural pauses. Monitor for END_SPEECH events that produce no transcript within 2 seconds.

3. **Speech fragmentation:** Have a caller speak a long sentence with natural breath pauses. Observe the transcript being split into 3-5 separate segments.

4. **Language misidentification:** Configure `language=unknown` (auto-detect) and have an Indian English speaker make a call.

5. **TTS gaps:** Send 3-4 consecutive text chunks of 30-50 characters each to bulbul:v3 via WebSocket. Measure the gap between the last audio byte of chunk N and the first audio byte of chunk N+1.

---

## 8. Our Asks

1. **STT:** Can the server-side VAD sensitivity be configurable? `high_vad_sensitivity=True` fragments natural speech.
2. **STT:** What causes END_SPEECH without a transcript? Is there a minimum audio duration?
3. **STT:** Is the repetition hallucination a known issue in streaming mode?
4. **STT:** Can auto-detect language have a confidence threshold before committing?
5. **TTS:** What's the expected TTFB for a 30-char chunk on bulbul:v3?
6. **TTS:** Does requesting 16kHz (non-native) add latency vs. 24kHz?
7. **TTS:** Can `min_buffer_size` go below 30 without quality loss?
8. **TTS:** Is progressive audio delivery possible (stream audio before full phrase is synthesized)?

---

*Companion document: Detailed audit report with call recordings for each issue.*
