# Sarvam STT + TTS Audit Report
**Date:** March 19, 2026
**Platform:** Wavelength Voice AI (Pipecat 0.0.104 + Plivo)
**Sarvam Models:** saaras:v3 (STT), bulbul:v3 (TTS)
**Sample Size:** 16 calls analyzed (11 STT transcript audit + 5 TTS audio audit)
**Languages:** English (en-IN), Tamil (ta-IN), Kannada (kn-IN), Auto-detect
**Period:** March 18-19, 2026

---

## Executive Summary

We audited 11 production calls using Sarvam STT (saaras:v3) and TTS (bulbul:v3). We found **critical reliability issues** in both STT and TTS that directly impact call quality and user experience.

**STT Issues:**
- 126x repetition hallucination from a single utterance
- 31 `END_SPEECH` events with no transcript returned across 6 calls
- Systematic speech fragmentation on calls > 60 seconds
- Garbled transcription of spoken Tamil
- Language misidentification (English detected as Hindi/Bengali)

**TTS Issues:**
- 23-71% of call duration is silence (audio gaps between phrases)
- Every recording had at least 2 gaps exceeding 3 seconds
- One call had a 14.1-second continuous silence gap (TTS stall)
- Volume inconsistency across calls (-30.9 dB to -22.7 dB mean)

---

## Part 1: STT Issues (saaras:v3)

### Issue 1: Repetition Hallucination (CRITICAL)

**Call:** Santhosh (+919176753253) | 43s | Call ID: 24c2549b
**Recording:** [Listen](https://aps1.media.plivo.com/v1/Account/MAYJNIZJDLYZUTMGJLNS/Recording/158053c9-bc53-4677-8e5c-2bc9ba5bafa2.mp3)

Sarvam produced the Tamil word "ok" repeated **126 times** from what was likely a single short acknowledgment:

```
User: "ok ok ok ok ok ok ok ok ok ok ok ok ok..." (126 repetitions)
```

The user did NOT say "ok" 126 times. The STT model entered a runaway repetition loop. This is a known failure mode in streaming ASR models where the decoder gets stuck in a loop.

**Impact:** The LLM received gibberish, the conversation failed completely.

---

### Issue 1b: Complete STT Failure — Zero Transcripts (CRITICAL)

**Call:** Smita (+919422521813) | 105s | Language: en-IN | Call ID: d83242ec
**Recording:** [Listen](https://aps1.media.plivo.com/v1/Account/MAYME0YWZKODUWMWJINJ/Recording/48998289-3d4f-4001-93de-a3f00657c17b.mp3)

105 seconds of call with **zero transcript turns**. The recording confirms the user spoke (audible in the recording) but Sarvam returned no transcripts at all. The bot played the greeting and silence watchdog messages, but never received any user speech.

Similarly affected: Preeti (+918977919651, 123s, 0 turns), Sindhuri (+917799533633, 52s, 0 turns).

**Impact:** Three calls with complete STT failure — users spoke but the bot never heard them.

---

### Issue 2: Transcript Drops — END_SPEECH with No Output (HIGH)

**Total:** 31 timeout events across 6 calls

| Call | Contact | Duration | Timeout Events | % Speech Lost |
|------|---------|----------|---------------|---------------|
| a55b8d9f | Dinesh | 137s | **13** | ~31% |
| ed4bd290 | Pramoth | 126s | **10** | ~24% |
| 24c2549b | Santhosh | 43s | 3 | ~17% |
| 041e5416 | Dinesh | 19s | 2 | ~33% |
| 9aeef8be | Yashwanth | 25s | 2 | ~40% |
| c7a422ed | Naveen | 11s | 1 | ~33% |

Sarvam's server-side VAD fires `END_SPEECH` indicating it detected speech, but the ASR engine returns no transcript. Our system logs this as `sarvam_stt_end_speech_timeout`. The user spoke, the system heard them, but no text was produced.

**Impact:** Bot goes silent (no response because no transcript to respond to), user thinks connection dropped. Silence watchdog fires "Hello? Can you hear me?" after 12.8s.

---

### Issue 3: Speech Fragmentation (HIGH)

**Affected calls:** Pramoth (126s, 5 instances), Dinesh (137s, 4 instances)

Sarvam's server-side VAD splits continuous speech into multiple small transcript segments. Example from Dinesh's call:

```
User turn 13: "No tablets."
User turn 14: "They're giving insulin injections."
```

This was one continuous sentence: "No tablets, they're giving insulin injections." Sarvam's VAD detected a brief pause (natural breath) and split it into two separate transcripts with an `END_SPEECH` between them.

**English example — Keerthi (+916309454017, 197s, en-IN):**
**Recording:** [Listen](https://aps1.media.plivo.com/v1/Account/MAMDLMNDE3MMUTM2QYZC/Recording/3169ac03-303f-43c9-b3ad-a4c3ed5ebfc0.mp3)

User's single thought split across 3 turns:
```
User turn 9:  "Hmm."
User turn 10: "mainly"
User turn 11: "Nana Nani."   ← garbled hallucination; user likely said their health concern
```

Later in the same call:
```
User turn 13: "Hello."        ← phantom word during bot speech
User turn 14: "Yeah, it's about 2 years now."
User turn 15: "It's been really affecting me."   ← continuation split into separate turn
```

**English example — Harini (+919538584904, 253s, en-IN):**
**Recording:** [Listen](https://aps1.media.plivo.com/v1/Account/MAYME0YWZKODUWMWJINJ/Recording/570070e3-3114-481b-beeb-da4d0e3802e0.mp3)

```
User turn 4: "Yeah, correct."
User turn 5: "Yeah correct correct"   ← same utterance split into two turns
```

Later, English transcribed as Kannada:
```
User turn 7:  "ಓಕೆ."                    ← user said "okay" in English, transcribed as Kannada
User turn 17: "ಮೊಬೈಲ್ ನಂಬರ್ � ゴット."    ← "mobile number I got" transcribed as Kannada
```

And a word hallucination:
```
User turn 13: "Massage"    ← user said "message", transcribed as "Massage"
```

**Pattern:** Fragmentation scales with call length. Short calls (11-25s) had zero fragmentation. Calls > 120s had 4-5 fragmentation instances each. **This affects both Tamil and English calls equally.**

**Impact:** The LLM sees fragmented user turns and makes wrong judgments — treating incomplete fragments as complete responses, or interpreting context-free fragments as "irrelevant answers."

---

### Issue 4: Language Misidentification (MEDIUM)

**Call:** Animesh (+919609775259) | 45s | language=unknown
**Recording:** [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/e13346f2-ff42-4084-a44b-d23750ca487c.mp3)

When using `language=unknown` (auto-detect mode), Sarvam misidentified English speech as:
- Hindi: `"लोग के नाम है।"` (transcribed from English)
- Bengali: `"হ্যাঁ হ্যাঁ স্পিকিং ইংলিশ ও হবে না।"` (transcribed from English)

The user was speaking English throughout. The bot responded: "I understand! Let me have a colleague who speaks your language call you back."

**Also observed in Harini's call** (en-IN mode, not auto-detect):
Even when language is explicitly set to `en-IN`, Sarvam occasionally transcribes English as Kannada script. User said "okay" → transcribed as `"ಓಕೆ."`. User said "mobile number I got" → transcribed as `"ಮೊಬೈಲ್ ನಂಬರ್ � ゴット."`.

**Impact:** Call terminated (on auto-detect) or bot confused (on en-IN) because the system received non-English text from an English speaker.

---

### Issue 5: STT Hallucinations — Phantom Words (MEDIUM)

**Call:** Animesh (+919609775259) | 45s
**Recording:** [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/779c4d16-34b1-417e-aab4-aa157009e939.mp3)

Sarvam transcribed hesitation sounds (thinking/pausing) as:
- `"Thank you."` — user was thinking, not saying "thank you"
- `"Bye."` — user was mid-thought, not saying goodbye

**Impact:** The LLM interpreted "Thank you" as conversation wrap-up and "Bye" as a goodbye signal, ending calls prematurely. Users lost in the middle of explaining themselves.

---

### Issue 6: Garbled Tamil Transcription (MEDIUM)

Multiple calls produced syntactically broken Tamil that no native speaker would recognize:
- `"நீ அப்ப நீ ட்ரீக் ஆக."` — meaningless
- `"நீ காலேஜ் குட்."` — "You college good" — nonsensical
- `"ஏய் கல்புற்றா, ஹலோ."` — garbled
- `"ஹெல்த்தியாக்குறாப்புல அவரு."` — partially intelligible but mangled

The STT appears to confuse phonemes in colloquial/spoken Tamil vs. formal written Tamil.

---

## Part 2: TTS Issues (bulbul:v3)

### Audio Quality Analysis — 5 Recordings

| Recording | Duration | Silence % | Gaps > 1.5s | Gaps > 3s | Worst Gap | Recording |
|-----------|----------|-----------|-------------|-----------|-----------|-----------|
| **Falguni** | 55s | **71.1%** | 8 | 3 | **14.1s** | [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/99ec9c6e-ec8c-4d65-85a4-5aa154fabf05.mp3) |
| **Dinesh** | 136s | **47.2%** | 20 | 3 | 4.3s | [Listen](https://aps1.media.plivo.com/v1/Account/MAYJNIZJDLYZUTMGJLNS/Recording/dc9faa97-2156-43f7-a4c5-d4f7deed26f8.mp3) |
| Pramoth | 126s | 44.5% | 19 | 3 | 4.0s | [Listen](https://aps1.media.plivo.com/v1/Account/MAYJNIZJDLYZUTMGJLNS/Recording/0c625466-fbd8-42bd-b385-f2b9c8da94cf.mp3) |
| SNA | 138s | 41.2% | 18 | 3 | 6.9s | [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/b8e1a810-68fb-4c89-9623-60d6428e4a80.mp3) |
| Sahil | 195s | 23.5% | 12 | 2 | 4.7s | [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/217413ae-4db7-4a5f-bbfd-b4c88b102aae.mp3) |

**Methodology:** FFmpeg silence detection at -40dB threshold, gaps > 0.5s counted. All recordings are stereo (left=bot, right=user).

### Issue 7: Catastrophic TTS Stall (CRITICAL)

**Call:** Falguni | 55s | 71.1% silence
**Recording:** [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/99ec9c6e-ec8c-4d65-85a4-5aa154fabf05.mp3)

A 14.1-second continuous silence gap at the 36-50 second mark. The TTS completely stalled — no audio was produced for 14 seconds. Two additional gaps of 5.5s and 5.9s. The caller heard mostly silence.

### Issue 8: Pervasive Inter-Phrase Audio Gaps (HIGH)

Every single recording has at least 2 gaps exceeding 3 seconds. The average silence percentage across all 5 recordings is **45.5%** — nearly half the call is dead air.

These gaps occur between TTS phrase chunks. Text is sent to bulbul:v3 in 30-50 character chunks. Between chunks, there's a delay before the next audio arrives. The caller hears complete silence during this gap.

**Specific examples (listen in recordings above):**

- **Falguni** — 14.1s gap at 0:36-0:50 (catastrophic stall), 5.9s at 0:06, 5.5s at 0:14
- **SNA** — 6.9s gap at 0:21, 4.4s at 0:52, 3.9s at 0:41
- **Dinesh** — 40 gaps total, averaging one every 3.4 seconds. Worst: 4.3s at 0:54, 3.5s at 0:72, 3.1s at 0:88. The choppy delivery makes the bot sound like it's on a broken connection.
- **Pramoth** — 3.3s gap at 1:37, 3.1s at 0:10. 44.5% silence makes conversation feel labored.
- **Sahil** — Best quality at 23.5% silence, but still has a 4.7s gap at 2:08 and clips at 0.0 dB (distortion).

### Issue 9: Silent/Noisy Audio Tails (MEDIUM)

bulbul:v3 occasionally emits a long near-silent or noisy audio tail after the spoken content has finished. We had to build a custom `TTSTailTrim` processor that detects low-energy audio frames (RMS < 90, max amplitude < 300) and drops them if they exceed 900ms.

Without this trim, the bot would appear to still be "speaking" (pipeline thinks audio is still flowing) even though the actual speech ended seconds ago. This delays turn transitions — the user waits for the bot to "finish" but it's just noise.

**Impact:** Without our workaround, adds 200ms-2s of dead noise after every bot utterance. With the trim, occasionally clips legitimate quiet endings.

---

### Issue 10: Volume Inconsistency (LOW)

- Falguni: -30.9 dB mean (very quiet — bot sounds faint)
- Sahil: 0.0 dB max (clipping — causes distortion)
- Range across calls: 8 dB spread in mean volume

---

## Part 3: Configuration Context

We use Sarvam through Pipecat 0.0.104's built-in `SarvamSTTService` and `SarvamTTSService`:

### STT Config
```
Model: saaras:v3
Sample rate: 16kHz
Server-side VAD: enabled (vad_signals=True, high_vad_sensitivity=True)
Language: en-IN (or auto-detect when unknown)
Connection: WebSocket streaming
```

### TTS Config
```
Model: bulbul:v3
Sample rate: 16kHz (native is 24kHz)
min_buffer_size: 30 chars
max_chunk_length: 100 chars
temperature: 0.7
Text aggregation: Adaptive (first phrase 30 chars, subsequent 50 chars)
Connection: WebSocket streaming
```

### Pipeline
```
Plivo WebSocket → SileroVAD → SmartTurn → Sarvam STT → Gemini LLM → Sarvam TTS → Plivo WebSocket
```

Full architecture details in the companion document: `sarvam-architecture-overview.md`

---

## Questions for Sarvam Team

### STT (saaras:v3)
1. What causes the repetition hallucination loop (126x "ok")? Is this a known issue with streaming mode?
2. Why does END_SPEECH fire without producing a transcript? We saw 31 instances across 6 calls. Is there a minimum audio duration threshold?
3. Can the server-side VAD sensitivity be tuned to reduce speech fragmentation? Current `high_vad_sensitivity=True` seems too aggressive for Indian English with natural pauses.
4. Auto-detect (`language=unknown`) misidentifies English as Hindi/Bengali — is there a confidence threshold we can set?
5. Are there known issues with colloquial Tamil transcription accuracy?

### TTS (bulbul:v3)
6. What's the expected time-to-first-audio for a 30-character text chunk? We see 700-3800ms.
7. Does requesting 16kHz output (non-native) add latency vs. native 24kHz?
8. What causes multi-second TTS stalls (14.1s observed)? Is this a server-side issue?
9. Can `min_buffer_size` be reduced below 30 without quality degradation? We want faster first-phrase delivery.
10. Is there a way to get streaming audio chunks before the full phrase is synthesized (progressive delivery)?

---

## Appendix: Call IDs + Recordings

| Call ID | Contact | Phone | Issue Type | Recording |
|---------|---------|-------|-----------|-----------|
| 24c2549b | Santhosh | +919176753253 | STT: Hallucination loop (126x repeat) | [Recording](https://aps1.media.plivo.com/v1/Account/MAYJNIZJDLYZUTMGJLNS/Recording/158053c9-bc53-4677-8e5c-2bc9ba5bafa2.mp3) |
| a55b8d9f | Dinesh | +918637451203 | STT: 13 timeouts, fragmentation | [Recording](https://aps1.media.plivo.com/v1/Account/MAYJNIZJDLYZUTMGJLNS/Recording/dc9faa97-2156-43f7-a4c5-d4f7deed26f8.mp3) |
| ed4bd290 | Pramoth | +919952711053 | STT: 10 timeouts, fragmentation | [Recording](https://aps1.media.plivo.com/v1/Account/MAYJNIZJDLYZUTMGJLNS/Recording/0c625466-fbd8-42bd-b385-f2b9c8da94cf.mp3) |
| 041e5416 | Dinesh | +918015646771 | STT: 2 timeouts (clean transcript) | [Recording](https://aps1.media.plivo.com/v1/Account/MAYJNIZJDLYZUTMGJLNS/Recording/c0ba7313-263d-4c4f-aed1-8a8b7a28a1ee.mp3) |
| c7a422ed | Naveen | +919551812203 | STT: IVR misidentified as speech | [Recording](https://aps1.media.plivo.com/v1/Account/MAYJNIZJDLYZUTMGJLNS/Recording/57180df2-7c1f-41b8-9bca-2a1c47280a18.mp3) |
| 9aeef8be | Yashwanth | +917842584025 | STT: Truncated transcript | [Recording](https://aps1.media.plivo.com/v1/Account/MAMDLMNDE3MMUTM2QYZC/Recording/b49dc2ce-a2b0-407d-87c4-06053de8d0a4.mp3) |
| 4817d2e0 | Falguni | +919606206785 | TTS: 14.1s stall, 71% silence | [Recording](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/99ec9c6e-ec8c-4d65-85a4-5aa154fabf05.mp3) |
| 2cfcf730 | SNA | +917875787518 | TTS: 41% silence, 6.9s gap | [Recording](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/b8e1a810-68fb-4c89-9623-60d6428e4a80.mp3) |
| f350ec8b | Keerthi | +916309454017 | STT: English fragmentation, hallucination ("Nana Nani") | [Recording](https://aps1.media.plivo.com/v1/Account/MAMDLMNDE3MMUTM2QYZC/Recording/3169ac03-303f-43c9-b3ad-a4c3ed5ebfc0.mp3) |
| cf593e46 | Harini | +919538584904 | STT: English→Kannada misidentification, "Massage" hallucination | [Recording](https://aps1.media.plivo.com/v1/Account/MAYME0YWZKODUWMWJINJ/Recording/570070e3-3114-481b-beeb-da4d0e3802e0.mp3) |
| d83242ec | Smita | +919422521813 | STT: Complete failure — 105s, 0 transcripts | [Recording](https://aps1.media.plivo.com/v1/Account/MAYME0YWZKODUWMWJINJ/Recording/48998289-3d4f-4001-93de-a3f00657c17b.mp3) |
| 354e018b | Preeti | +918977919651 | STT: Complete failure — 123s, 0 transcripts | [Recording](https://aps1.media.plivo.com/v1/Account/MAYME0YWZKODUWMWJINJ/Recording/df15a4c0-0911-481d-a46c-5e0c5d5a280e.mp3) |
| 1eeb61b0 | Sindhuri | +917799533633 | STT: Complete failure — 52s, 0 transcripts | [Recording](https://aps1.media.plivo.com/v1/Account/MAYME0YWZKODUWMWJINJ/Recording/a8057e80-d8bc-4d9b-8c52-6e421056aed6.mp3) |
| c63e7dd6 | Sahil | +919817562070 | TTS: 23.5% silence, clipping | [Recording](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/217413ae-4db7-4a5f-bbfd-b4c88b102aae.mp3) |
| a55b8d9f | Dinesh | +918637451203 | TTS: 47% silence, 40 gaps | [Recording](https://aps1.media.plivo.com/v1/Account/MAYJNIZJDLYZUTMGJLNS/Recording/dc9faa97-2156-43f7-a4c5-d4f7deed26f8.mp3) |
| ed4bd290 | Pramoth | +919952711053 | TTS: 44.5% silence, 35 gaps | [Recording](https://aps1.media.plivo.com/v1/Account/MAYJNIZJDLYZUTMGJLNS/Recording/0c625466-fbd8-42bd-b385-f2b9c8da94cf.mp3) |
