# Wavelength + Sarvam AI: Technical Architecture Overview

**Audience:** Sarvam Engineering Team
**Date:** 2026-03-19
**Wavelength Version:** v3
**Pipecat Version:** 0.0.104

---

## 1. System Overview

Wavelength is a multi-tenant AI voice calling platform for Indian coaches and businesses. It makes outbound calls (sales, follow-ups, appointment reminders) and handles inbound calls using an AI agent that speaks naturally in Indian English and Indian regional languages.

### Technology Stack

| Component | Technology |
|-----------|-----------|
| Voice Pipeline Framework | Pipecat 0.0.104 (open-source, by Daily.co) |
| Telephony | Plivo (primary), Twilio (secondary) |
| STT | Sarvam AI (`saaras:v3`) |
| TTS | Sarvam AI (`bulbul:v3`) |
| LLM | Google Gemini 2.5 Flash |
| Local VAD | Silero VAD |
| Turn Detection | SmartTurn v3.2 (Pipecat's ML-based turn predictor) |
| Server | FastAPI (Python), deployed on GCP VM |

### How a Call Works

1. Plivo/Twilio initiates a phone call to the contact.
2. When the call connects, Plivo opens a bidirectional WebSocket to our server.
3. Our server builds a per-call Pipecat pipeline with STT, LLM, and TTS services.
4. Audio flows through the pipeline in real-time until the call ends.

---

## 2. Audio Format and Flow

### Telephony Audio Format

Plivo bidirectional streams use **raw PCM 16-bit signed little-endian at 16kHz mono** (`audio/x-l16;rate=16000`). No mulaw conversion or resampling is involved. Audio is exchanged as base64-encoded payloads inside JSON WebSocket messages.

- **Frame size:** 20ms at 16kHz = 640 bytes per frame
- **Inbound (user audio):** Plivo sends `media` events with base64-encoded PCM
- **Outbound (bot audio):** We send `playAudio` events with base64-encoded PCM
- **Interruption:** We send `clearAudio` events to flush Plivo's playback buffer

### Pipeline Architecture

```
                          Pipecat Pipeline (per-call)
                          ===========================

  Plivo                                                              Plivo
  Phone ──WebSocket──►  Transport.input()                            Phone
  (PCM                      │                                   ◄──WebSocket──
  16kHz)                     ▼                                      (PCM
                     Sarvam STT (saaras:v3)                         16kHz)
                     [WebSocket, server-side VAD]                      ▲
                             │                                         │
                             ▼                                   Transport.output()
                     CallGuard + LatencyTracker                        ▲
                             │                                         │
                             ▼                                   LatencyTracker
                     SilenceWatchdog                                   ▲
                             │                                         │
                             ▼                                    TTSTailTrim
                     ContextAggregator.user()                          ▲
                             │                                         │
                             ▼                                  Sarvam TTS (bulbul:v3)
                     Gemini 2.5 Flash LLM ──────────────────►  [WebSocket streaming]
                     [generates response text]              [with PhraseTextAggregator]
```

### Frame Flow Detail

1. **Inbound:** Plivo WebSocket `media` event -> `PlivoPCMFrameSerializer.deserialize()` -> `InputAudioRawFrame(sample_rate=16000, num_channels=1)`
2. **STT:** `InputAudioRawFrame` -> Sarvam STT WebSocket -> `TranscriptionFrame` (text)
3. **LLM:** Transcript accumulated in context -> Gemini generates response -> `LLMTextFrame` stream
4. **TTS:** Text chunks (via `PhraseTextAggregator`) -> Sarvam TTS WebSocket -> `TTSAudioRawFrame`
5. **Outbound:** `TTSAudioRawFrame` -> `PlivoPCMFrameSerializer.serialize()` -> Plivo WebSocket `playAudio`

---

## 3. Sarvam STT Integration

### Configuration

```python
stt = SarvamSTTService(
    api_key=SARVAM_API_KEY,
    model="saaras:v3",
    sample_rate=16000,
    input_audio_codec="wav",
    params=SarvamSTTService.InputParams(
        language=<PipecatLanguage enum or None>,  # None = auto-detect
        mode="transcribe",
        vad_signals=True,
        high_vad_sensitivity=True,
    ),
    keepalive_timeout=30.0,
)
```

### Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `model` | `saaras:v3` | Latest Sarvam STT model |
| `sample_rate` | `16000` | Matches Plivo's native 16kHz PCM -- no resampling needed |
| `input_audio_codec` | `wav` | PCM audio format |
| `mode` | `transcribe` | Standard transcription mode |
| `vad_signals` | `True` | Server-side VAD enabled -- Sarvam sends `START_SPEECH` / `END_SPEECH` events |
| `high_vad_sensitivity` | `True` | More aggressive speech detection |
| `keepalive_timeout` | `30.0` | Seconds before WebSocket keepalive ping |

### Language Configuration

| Call Language Setting | Sarvam Language Param | Behavior |
|-----------------------|----------------------|----------|
| `en-IN` | `Language.EN_IN` | Explicit Indian English |
| `hi-IN` | `Language.HI_IN` | Explicit Hindi |
| `ta-IN`, `te-IN`, `bn-IN`, etc. | Corresponding `Language.*` enum | Explicit regional language |
| `unknown` or `multi` | `None` | Falls back to Sarvam auto-detect |

Supported language mappings: `hi-IN`, `bn-IN`, `gu-IN`, `kn-IN`, `ml-IN`, `mr-IN`, `ta-IN`, `te-IN`, `pa-IN`, `or-IN`, `as-IN`, `ur-IN`, `en-IN`.

### `_SafeSarvamSTT` Wrapper

We wrap `SarvamSTTService` in a custom `_SafeSarvamSTT` class that fixes two critical timing issues in the Pipecat <-> Sarvam interaction:

#### Fix 1: No `broadcast_interruption` on `START_SPEECH`

When Sarvam sends a `START_SPEECH` event, we broadcast `UserStartedSpeakingFrame` but **do NOT call `broadcast_interruption()`**. This prevents cascade cancellations that would kill in-flight LLM generation and TTS audio playback. Instead, interruptions are handled by Pipecat's `MinWordsInterruptionStrategy`, which only interrupts when the user has spoken at least 2 transcribed words.

#### Fix 2: Buffered `END_SPEECH` (the transcript ordering problem)

This is the most important fix. Here is the problem:

1. Sarvam sends `END_SPEECH` event (type: `events`, signal: `END_SPEECH`)
2. Sarvam sends transcript `data` message (type: `data`, with `transcript` field)
3. These arrive as **two separate WebSocket messages**, with `END_SPEECH` first

If we immediately broadcast `UserStoppedSpeakingFrame` on `END_SPEECH`, Pipecat's context aggregator receives it **before** the transcript arrives. The aggregator sees empty aggregation and does not push to the LLM. The transcript arrives later but nothing triggers `push_aggregation`. Result: **the user's speech is silently dropped**.

Our fix:

```
END_SPEECH arrives:
  1. Set _end_speech_pending = True
  2. Start a 2-second safety timeout
  3. Do NOT broadcast UserStoppedSpeakingFrame yet

Transcript DATA arrives:
  1. Cancel the safety timeout
  2. Process transcript (creates TranscriptionFrame, flows to aggregator)
  3. NOW broadcast UserStoppedSpeakingFrame
  4. Aggregator sees transcript in buffer, pushes to LLM

Safety timeout (2s, no transcript):
  1. Broadcast UserStoppedSpeakingFrame anyway
  2. Log as "sarvam_stt_end_speech_timeout"
```

#### Fix 3: Short audio hallucination filter

When `audio_duration` from Sarvam's metrics is < 0.5 seconds, we drop the transcript. Very short audio segments produce hallucinated transcripts like "Thank you", "Bye", or "Hmm" from background noise or hesitation sounds.

#### Fix 4: VADUserStoppedSpeakingFrame interception

When local Silero VAD fires `VADUserStoppedSpeakingFrame`, we intercept it and apply the same buffering logic as `END_SPEECH` -- we flush Sarvam's WebSocket client and wait for the transcript before broadcasting the stop frame. This prevents the same race condition from the local VAD path.

#### Fix 5: Language switching

`_update_settings()` handles runtime language changes by disconnecting and reconnecting the Sarvam WebSocket with the new language parameter.

### How START_SPEECH / END_SPEECH Events Are Handled

```
Sarvam WS Message (type="events"):
  ├── signal=START_SPEECH
  │     → Start metrics
  │     → Call on_speech_started event handler
  │     → Broadcast UserStartedSpeakingFrame (NO interruption broadcast)
  │
  └── signal=END_SPEECH
        → Call on_speech_stopped event handler
        → Set _end_speech_pending = True
        → Start 2s safety timeout task
        → Wait for transcript data message

Sarvam WS Message (type="data"):
  → Cancel safety timeout
  → Check audio_duration: if < 0.5s, drop transcript (hallucination filter)
  → Otherwise: process transcript via parent class → broadcast UserStoppedSpeakingFrame
```

---

## 4. Sarvam TTS Integration

### Configuration

```python
tts = SarvamTTSService(
    api_key=SARVAM_API_KEY,
    model="bulbul:v3",
    voice_id=<per-bot voice selection>,
    sample_rate=16000,
    text_aggregator=PhraseTextAggregator(
        min_phrase_chars=30,
        subsequent_phrase_chars=50,
        adaptive=True,
    ),
    params=SarvamTTSService.InputParams(
        language="en-IN",     # or per-call language
        min_buffer_size=30,
        max_chunk_length=100,
        temperature=0.7,
    ),
)
```

### Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `model` | `bulbul:v3` | Latest Sarvam TTS model |
| `voice_id` | Per-bot config | Selected voice for this bot |
| `sample_rate` | `16000` | Matches Plivo's 16kHz. Note: Sarvam's native output is 24kHz; requesting 16kHz means server-side downsampling |
| `language` | `en-IN` (default) | TTS language, falls back to `en-IN` for `unknown`/`multi` |
| `min_buffer_size` | `30` | Minimum characters before TTS synthesis starts |
| `max_chunk_length` | `100` | Maximum characters per TTS chunk |
| `temperature` | `0.7` | TTS variation/expressiveness |

### Text Chunking: PhraseTextAggregator

LLM output arrives as a stream of tokens. Rather than waiting for complete sentences, we split text at phrase boundaries (commas, semicolons, colons) in addition to sentence endings (periods, exclamation marks, question marks). This reduces time-to-first-audio by approximately 300-600ms.

**Adaptive behavior:**

- **First phrase:** `min_phrase_chars=30` -- lower threshold for fast time-to-first-byte (TTFB)
- **Subsequent phrases:** `subsequent_phrase_chars=50` -- higher threshold to reduce the number of TTS round-trips and inter-phrase audio gaps

Sentence endings (`.`, `!`, `?`) always trigger a split regardless of character count. Phrase delimiters (`,`, `;`, `:`) only trigger a split when accumulated text meets the character threshold.

On interruption, the aggregator resets to the first-phrase threshold so the next response starts with fast TTFB.

### TOKEN vs SENTENCE Mode

We use the default SENTENCE aggregation mode (via `PhraseTextAggregator`), not TOKEN mode. TOKEN mode deadlocks with Sarvam's `pause_frame_processing=True` behavior: each token triggers `run_tts()` which pauses the processor, but single tokens are below `min_buffer_size` so Sarvam never returns audio, the processor stays paused, and no more tokens flow.

### TTSTailTrim

A custom `TTSTailTrim` processor sits after Sarvam TTS in the pipeline. Sarvam occasionally emits a long near-silent tail after spoken content finishes. The trimmer buffers low-energy frames (RMS < 90, max amplitude < 300) and drops them if:

- The low-energy tail exceeds 900ms, OR
- A `TTSStoppedFrame` arrives while low-energy frames are still buffered

This prevents audible noise artifacts on the phone line.

### BOT_VAD_STOP_SECS Monkey-Patch

```python
import pipecat.transports.base_output as _base_output
_base_output.BOT_VAD_STOP_SECS = 1.5  # Default is 0.35s
```

Sarvam TTS has inter-phrase audio gaps of approximately 700-1500ms (the time between the last audio frame of one phrase and the first audio frame of the next phrase). Pipecat's default `BOT_VAD_STOP_SECS=0.35` would trigger a false `BotStoppedSpeakingFrame` mid-sentence, clearing audio buffers and causing audible drops.

We increase this to **1.5 seconds** to tolerate Sarvam's inter-phrase gaps. This is safe because user interruptions use `MinWordsInterruptionStrategy` (transcript-based, requires 2+ words), not bot-speaking state.

---

## 5. Turn Detection Architecture

Turn detection determines when the user has finished speaking and it is the bot's turn to respond. We use a three-layer system:

### Layer 1: Local Silero VAD

```python
vad_analyzer=SileroVADAnalyzer(params=VADParams(
    stop_secs=0.5,
    min_volume=0.5,
))
```

Runs locally on every audio frame. Detects when the user starts and stops producing sound. This provides `UserStartedSpeakingFrame` and `UserStoppedSpeakingFrame` to the pipeline. `vad_audio_passthrough=True` means audio continues flowing to STT even during detected silence.

### Layer 2: SmartTurn v3.2 (ML Turn Predictor)

```python
turn_analyzer=LocalSmartTurnAnalyzerV3(
    params=SmartTurnParams(stop_secs=1.0),
)
```

SmartTurn is Pipecat's ML-based turn prediction model. When Silero VAD detects silence, SmartTurn analyzes the accumulated transcript and context to predict whether the user is truly done speaking or just pausing mid-thought.

- `stop_secs=1.0` -- SmartTurn has up to 1.0 second of silence to make its prediction before forcing a turn completion
- This is set higher than the default because Sarvam's server-side VAD fragments speech into short segments. With `stop_secs=0.3`, SmartTurn's INCOMPLETE verdict had no time to hold, and every fragment forced a turn completion

### Layer 3: Sarvam Server-Side VAD

With `vad_signals=True` and `high_vad_sensitivity=True`, Sarvam's server sends `START_SPEECH` and `END_SPEECH` events independent of local VAD. These events:

- Trigger `UserStartedSpeakingFrame` / `UserStoppedSpeakingFrame` via our `_SafeSarvamSTT` wrapper
- Provide speech boundary signals at the STT level (after Sarvam has analyzed the audio)

### How the Three Layers Interact

```
User speaks
    │
    ├─► Silero VAD detects speech → UserStartedSpeakingFrame
    │   (local, ~20ms latency)
    │
    ├─► Sarvam server-side VAD detects speech → START_SPEECH event
    │   → _SafeSarvamSTT broadcasts UserStartedSpeakingFrame
    │
    │   [User speaking... audio flows to Sarvam STT]
    │
    ├─► Silero VAD detects 0.5s silence → VADUserStoppedSpeakingFrame
    │   → _SafeSarvamSTT intercepts, buffers, flushes Sarvam
    │
    ├─► Sarvam server-side VAD detects end → END_SPEECH event
    │   → _SafeSarvamSTT buffers, waits for transcript
    │
    ├─► Sarvam sends transcript data
    │   → _SafeSarvamSTT broadcasts UserStoppedSpeakingFrame
    │
    └─► SmartTurn evaluates: is the user done?
        ├── COMPLETE → trigger turn, push to LLM
        └── INCOMPLETE → hold for up to 1.0s, wait for more speech
```

### Interruption Strategy

```python
PipelineParams(
    allow_interruptions=True,
    interruption_strategies=[MinWordsInterruptionStrategy(min_words=2)],
)
```

The bot can be interrupted, but only when the user has spoken at least 2 transcribed words. This prevents interruptions from noise, echo, or single-word hesitations ("um", "uh").

---

## 6. Known Issues We Have Observed

These are behavioral issues we have encountered in production. We document them here for Sarvam's awareness; a separate audit report covers detailed analysis.

### STT Issues

1. **Transcript drops (`sarvam_stt_end_speech_timeout`):** Sarvam sends `END_SPEECH` but never sends the corresponding transcript `data` message. Our 2-second safety timeout fires, and the user's speech is lost. We see this in logs as `sarvam_stt_end_speech_timeout`.

2. **Speech fragmentation from server-side VAD:** Sarvam's server-side VAD sometimes fragments a single user utterance into multiple `START_SPEECH` / `END_SPEECH` cycles. Each fragment produces a partial transcript. With SmartTurn's 1.0s `stop_secs`, we mitigate most premature turn completions, but rapid fragments can still cause issues.

3. **Hallucinated transcripts from hesitation sounds:** Short audio segments (< 0.5s, typically hesitation sounds like "hmm", breathing, or background noise) produce confident but incorrect transcripts such as "Thank you", "Bye", "Yes", or "OK". We filter these using `audio_duration < 0.5` from Sarvam's metrics, but some slip through at slightly longer durations.

4. **Language misidentification on auto-detect:** When `language=None` (auto-detect mode, used for `unknown`/`multi` language settings), Sarvam occasionally misidentifies the language, producing garbled or incorrect transcripts. This is most common with Indian English speakers who code-switch between English and Hindi.

### TTS Issues

5. **Inter-phrase audio gaps:** Between TTS phrases, there is a gap of approximately 700-1500ms where no audio is produced. This creates perceivable silence on the phone line mid-sentence. We mitigate this with `BOT_VAD_STOP_SECS=1.5` (preventing false bot-stopped events) and optionally with a ComfortNoiseInjector (currently disabled).

6. **Latency spikes on first phrase:** The first TTS phrase of a response sometimes has higher latency than subsequent phrases, likely due to WebSocket connection warm-up or model loading. Our `PhraseTextAggregator` with `min_phrase_chars=30` ensures the first chunk is long enough to avoid wasting a round-trip on a very short phrase.

7. **Silent tail artifacts:** Sarvam TTS occasionally emits a long near-silent tail (low RMS, low max amplitude) after the spoken content. Our `TTSTailTrim` processor detects and drops tails exceeding 900ms of low-energy audio.

---

## 7. Our Full Configuration

### Sarvam STT Configuration

```python
# Service instantiation
SarvamSTTService(
    api_key=SARVAM_API_KEY,
    model="saaras:v3",
    sample_rate=16000,
    input_audio_codec="wav",
    params=SarvamSTTService.InputParams(
        language=None,               # or Language.EN_IN, Language.HI_IN, etc.
        mode="transcribe",
        vad_signals=True,
        high_vad_sensitivity=True,
    ),
    keepalive_timeout=30.0,
)
```

### Sarvam TTS Configuration

```python
# Service instantiation
SarvamTTSService(
    api_key=SARVAM_API_KEY,
    model="bulbul:v3",
    voice_id="<per-bot-voice>",
    sample_rate=16000,
    text_aggregator=PhraseTextAggregator(
        min_phrase_chars=30,
        subsequent_phrase_chars=50,
        adaptive=True,
    ),
    params=SarvamTTSService.InputParams(
        language="en-IN",
        min_buffer_size=30,
        max_chunk_length=100,
        temperature=0.7,
    ),
)
```

### Transport / VAD / Turn Detection Configuration

```python
# Audio transport
FastAPIWebsocketParams(
    audio_out_enabled=True,
    audio_out_sample_rate=16000,
    audio_out_10ms_chunks=10,
    add_wav_header=False,
    serializer=PlivoPCMFrameSerializer(...),
    vad_enabled=True,
    vad_audio_passthrough=True,
    vad_analyzer=SileroVADAnalyzer(params=VADParams(
        stop_secs=0.5,
        min_volume=0.5,
    )),
    turn_analyzer=LocalSmartTurnAnalyzerV3(
        params=SmartTurnParams(stop_secs=1.0),
    ),
)

# Pipeline-level
PipelineParams(
    allow_interruptions=True,
    interruption_strategies=[MinWordsInterruptionStrategy(min_words=2)],
    enable_metrics=True,
    enable_usage_metrics=True,
)

# Global monkey-patch
pipecat.transports.base_output.BOT_VAD_STOP_SECS = 1.5
```

### Feature Flags (app/config.py)

| Flag | Default | Description |
|------|---------|-------------|
| `ADAPTIVE_PHRASE_CHARS` | `True` | Adaptive phrase aggregation (lower first-phrase, higher subsequent) |
| `COMFORT_NOISE_ENABLED` | `False` | Pink noise injection during TTS inter-phrase gaps |
| `ECHO_GATE_ENABLED` | `True` | Mutes incoming audio during bot speech (echo suppression) |
| `ECHO_TAIL_MS` | `250.0` | Delay after bot stops before echo gate opens |
| `PLIVO_NOISE_CANCEL` | `True` | Plivo server-side noise cancellation on incoming audio |

### Pipeline Order

```
Transport.input()
  → Sarvam STT (_SafeSarvamSTT)
    → CallGuard
      → LatencyTracker (post_stt)
        → SilenceWatchdog
          → ContextAggregator.user()
            → Gemini LLM
              → Sarvam TTS
                → TTSTailTrim
                  → LatencyTracker (post_tts)
                    → Transport.output()
                      → ContextAggregator.assistant()
```

---

## Appendix: Key Source Files

| File | Description |
|------|-------------|
| `app/pipeline/factory.py` | Per-call pipeline builder, `_SafeSarvamSTT` wrapper, all service configuration |
| `app/serializers/plivo_pcm.py` | Plivo PCM 16kHz serializer, audio frame encode/decode |
| `app/pipeline/phrase_aggregator.py` | `PhraseTextAggregator` -- adaptive text chunking for TTS |
| `app/config.py` | Feature flags and environment configuration |
| `app/pipeline/silence_watchdog.py` | Polling-based silence detection (replaces UserIdleProcessor) |
