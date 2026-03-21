# Sarvam Ongoing Issues Log
**Started:** March 19, 2026 (post initial meeting)
**Updated:** March 20, 2026

---

## Issue Log

### 2026-03-21 — TTS TTFB spikes causing audio drops (600ms–2.5s)

**Config:** bulbul:v3, speaker=simran, en-IN, linear16 @ 16kHz
**Call:** +918105445777 | Call SID: 2c013506-0013-4702-a0da-031e9222ffaf | Bot: 150e4b39

**Sarvam TTS consistently slow across all turns, with one severe spike:**

| Turn | LLM TTFB | TTS TTFB | E2E Latency |
|------|----------|----------|-------------|
| 1 | 2ms | 1058ms | 1062ms |
| 2 | 21ms | 632ms | 698ms |
| 3 | 546ms | 604ms | 1156ms |
| 5 | 511ms | 609ms | 1124ms |
| 9 | 23ms | 1077ms | 1128ms |
| 10 | 581ms | **2547ms** | **3146ms** |

**Impact:** User hears noticeable pauses/drops between bot sentences. Turn 10 had a 3.1s gap — feels like the bot froze. LLM (Gemini) responds in 2-55ms; TTS is the sole bottleneck.

**Note:** Not a code issue — Gemini TTS on same infra returns audio in <200ms. This is Sarvam TTS baseline latency + occasional spikes. `min_buffer_size=30` may contribute (waits for 30 chars before sending to Sarvam).

---

### 2026-03-20 — TTS model unavailable/overloaded, 120s+ TTFB

**Config:** bulbul:v3, speaker=simran, en-IN, linear16 @ 16kHz
**Calls:** Animesh (+919609775259) | Multiple calls between 15:08–15:12 UTC

**Sarvam TTS WebSocket returning "model is unavailable or overloaded":**
- `SarvamTTSService error: TTS Error: error model is unavailable or overloaded`
- TTFB of **124–133 seconds** (should be <500ms)
- WebSocket also threw `Incorrect padding` error during reconnect
- Service reconnected on attempt 1 but remained slow

**Impact:** Bot appears completely silent to the caller. Greeting pre-synthesis fails (`greeting_synth_empty`), fallback TTS also takes 2+ minutes. Caller hears nothing, says "hello" repeatedly, hangs up or watchdog disconnects after ~13 seconds. Call summary says "user seemed to have trouble hearing."

**Logs:**
```
15:08:35 [warning] greeting_synth_empty  call_sid=5f19d113
15:10:53 | ERROR | SarvamTTSService#3 error: TTS Error: error model is unavailable or overloaded
15:10:53 | DEBUG | SarvamTTSService#3 TTFB: 133.630s
15:12:48 | DEBUG | SarvamTTSService#5 TTFB: 124.644s
```

**Note:** This is a Sarvam-side outage, not a code bug. All audio pipeline code is working correctly — the greeting text was properly generated with the customer's name.

---

### 2026-03-19 — Translate mode: END_SPEECH timeouts + language flip-flopping

**Config:** saaras:v3, mode=translate, language=unknown (auto-detect)
**Call:** Animesh (+919609775259) | 59s | Call ID: b160d8ca

**5 `end_speech_timeout` events** in a single 59-second call. Sarvam detected speech (fired END_SPEECH) but returned no transcript 5 times.

**Language misidentification in translate mode:**
- User said "Hello" in English → transcribed with `language_code=gu-IN` (Gujarati)
- Next "Hello" correctly identified as `en-IN`

**Garbled transcription:**
- User said "software engineering" → STT produced `"Sports Engineering"`
- User said "I just wanted to learn some new AI tools" → STT produced `"Yes, but soft."` + `"New Air Tools"` (fragmented + garbled)

**Impact:** Bot went silent for ~8 seconds during the timeout gaps. User said "Hello, hello" repeatedly. Bot then restarted the introduction from scratch, thinking the conversation had reset.

**Recording:** [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/cf2094ea-cab3-4411-993b-581fcb5d2fe0.mp3)
