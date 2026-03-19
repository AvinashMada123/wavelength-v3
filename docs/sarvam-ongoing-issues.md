# Sarvam Ongoing Issues Log
**Started:** March 19, 2026 (post initial meeting)
**Updated:** March 19, 2026

---

## Issue Log

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

**Recording:** Available in call logs (Call ID: b160d8ca-5e9a-45fc-ae9f-bc9e5a64584a)
