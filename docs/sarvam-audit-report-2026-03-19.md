# Sarvam STT + TTS Audit Report
**Date:** March 19, 2026
**Platform:** Wavelength Voice AI (Pipecat 0.0.104 + Plivo)
**Sarvam Models:** saaras:v3 (STT), bulbul:v3 (TTS)
**Sample Size:** 11 calls analyzed (6 STT transcript audit + 5 TTS audio audit)
**Period:** March 19, 2026 (last 24 hours)

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

Sarvam produced the Tamil word "ok" repeated **126 times** from what was likely a single short acknowledgment:

```
User: "ok ok ok ok ok ok ok ok ok ok ok ok ok..." (126 repetitions)
```

The user did NOT say "ok" 126 times. The STT model entered a runaway repetition loop. This is a known failure mode in streaming ASR models where the decoder gets stuck in a loop.

**Impact:** The LLM received gibberish, the conversation failed completely.

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

**Pattern:** Fragmentation scales with call length. Short calls (11-25s) had zero fragmentation. Calls > 120s had 4-5 fragmentation instances each.

**Impact:** The LLM sees fragmented user turns and makes wrong judgments — treating incomplete fragments as complete responses, or interpreting context-free fragments as "irrelevant answers."

---

### Issue 4: Language Misidentification (MEDIUM)

**Call:** Animesh (+919609775259) | 45s | language=unknown

When using `language=unknown` (auto-detect mode), Sarvam misidentified English speech as:
- Hindi: `"लोग के नाम है।"` (transcribed from English)
- Bengali: `"হ্যাঁ হ্যাঁ স্পিকিং ইংলিশ ও হবে না।"` (transcribed from English)

The user was speaking English throughout. The bot responded: "I understand! Let me have a colleague who speaks your language call you back."

**Impact:** Call terminated because the system thought the user spoke a different language.

---

### Issue 5: STT Hallucinations — Phantom Words (MEDIUM)

**Call:** Animesh (+919609775259) | 45s

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

| Recording | Duration | Total Silence | Silence % | Gaps > 1.5s | Gaps > 3s | Worst Gap |
|-----------|----------|---------------|-----------|-------------|-----------|-----------|
| **Falguni** | 55s | 39.1s | **71.1%** | 8 | 3 | **14.1s** |
| **Dinesh** | 136s | 64.4s | **47.2%** | 20 | 3 | 4.3s |
| Pramoth | 126s | 55.9s | 44.5% | 19 | 3 | 4.0s |
| SNA | 138s | 57.0s | 41.2% | 18 | 3 | 6.9s |
| Sahil | 195s | 45.9s | 23.5% | 12 | 2 | 4.7s |

**Methodology:** FFmpeg silence detection at -40dB threshold, gaps > 0.5s counted.

### Issue 7: Catastrophic TTS Stall (CRITICAL)

**Call:** Falguni | 55s | 71.1% silence

A 14.1-second continuous silence gap at the 36-50 second mark. The TTS completely stalled — no audio was produced for 14 seconds. Two additional gaps of 5.5s and 5.9s. The caller heard mostly silence.

### Issue 8: Pervasive Inter-Phrase Audio Gaps (HIGH)

Every single recording has at least 2 gaps exceeding 3 seconds. The average silence percentage across all 5 recordings is **45.5%** — nearly half the call is dead air.

These gaps occur between TTS phrase chunks. When the PhraseTextAggregator sends text to bulbul:v3, there is a delay before the next phrase's audio arrives. During this delay, the caller hears complete silence.

### Issue 9: Volume Inconsistency (LOW)

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

## Appendix: Call IDs for Reference

| Call ID | Contact | Phone | Issue Type |
|---------|---------|-------|-----------|
| 24c2549b | Santhosh | +919176753253 | Hallucination loop |
| a55b8d9f | Dinesh | +918637451203 | 13 timeouts, fragmentation |
| ed4bd290 | Pramoth | +919952711053 | 10 timeouts, fragmentation |
| Animesh test | Animesh | +919609775259 | Language misidentification, phantom words |
| 4817d2e0 | Falguni | +919606206785 | 14.1s TTS stall, 71% silence |
| 2cfcf730 | SNA | +917875787518 | 41% silence, 6.9s gap |
