# Sarvam STT + TTS Audit Report
**Date:** March 19, 2026
**Platform:** Wavelength Voice AI (Pipecat 0.0.104 + Plivo)
**Sarvam Models:** saaras:v3 (STT), bulbul:v3 (TTS)
**Sample Size:** 1000+ calls audited, 25+ specific examples with recordings
**Languages:** English (en-IN), Tamil (ta-IN), Kannada (kn-IN), Auto-detect
**Period:** March 5-19, 2026

---

## Executive Summary

We audited production calls using Sarvam STT (saaras:v3) and TTS (bulbul:v3) across 1000+ calls. We found **critical reliability issues** in both STT and TTS that directly impact call quality and user experience.

**STT Issues:**
- Garbled transcription of Indian-accented English ("Operations" → "Non pepper pressure")
- Echo/feedback loop — bot's own speech transcribed as user input
- Complete STT failure — zero transcripts on 52-123 second calls
- 31 `END_SPEECH` events with no transcript returned across 6 calls
- Speech fragmentation — continuous speech split into 3-5 tiny segments
- Repetition hallucination (126x loop from single utterance)
- Language misidentification (English detected as Hindi/Bengali/Kannada)
- Phantom word hallucination ("Thank you", "Bye" from hesitation sounds)
- WebSocket connection dropping mid-call after ~60s inactivity

**TTS Issues:**
- Users explicitly reporting "voice is breaking" and "voice is getting cut"
- 23-71% of call duration is silence (audio gaps between phrases)
- 14.1-second continuous TTS stall
- Silent/noisy audio tails requiring custom trimming
- Volume inconsistency across calls
- Concurrency issues under 50+ simultaneous calls

---

## Part 1: STT Issues — English (saaras:v3)

### Issue 1: Garbling Indian-Accented English (CRITICAL)

Sarvam STT consistently transcribes Indian-accented English words as complete nonsense.

| Contact | Phone | Duration | What User Said | What STT Produced | Recording |
|---------|-------|----------|---------------|-------------------|-----------|
| Finney | +919821906612 | 209s | "Operations" | "Non pepper pressure" | [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/7bf1ce6b-800e-428b-9082-592bf81cc1e7.mp3) |
| Ajay | +917738994478 | 58s | Job-related word | "Whole pizza" | [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/280372f3-8763-4953-8bc8-7f654532a12c.mp3) |
| Rajesh | +919987321501 | 54s | Something about AI | "The pizzas" | [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/2a25b187-3588-4033-8418-30144320bb1f.mp3) |
| Swati | +919167976554 | 89s | "I'm in HR" | "I'm in a chat" | [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/7e5b5b4f-6bea-4f36-b8e8-2d3b84fb14ca.mp3) |
| Gaurang | +917045393733 | 171s | Something specific | "For EA" | [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/36a0c62e-5ebf-4611-8178-32a8f1a129a4.mp3) |
| Bavaji | +919052143512 | 201s | Multiple garbled turns | "artificial ingredients" | [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/bcdaf4db-63b0-409f-bc0f-0cdcd0c9d6eb.mp3) |

**Impact:** When STT garbles the user's profession or answer, the bot either asks the same question again (user feels unheard) or responds to nonsense (destroys trust). Directly causes early call drops and user frustration.

**Ask:** Better handling of Indian English accents (South Indian, Hindi-influenced), Hinglish code-switching, and confidence scores per transcript segment so we can detect garbling.

---

### Issue 2: Echo/Feedback Loop — Transcribing Bot's Own Audio (CRITICAL)

Sarvam STT picks up the bot's TTS output from the user's phone speaker and transcribes it as user speech.

**Call:** Talha (+919696975211) | 174s
**Recording:** [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/46bb8365-9ab6-47f3-b6bf-c47ea021fcc7.mp3)

Specific echo instances:
- Bot said: "So you just signed up for Avinash sir's AI masterclass na?"
  STT transcribed user as: `"Yeah. So you just signed up for Avinash dot AI"`
- Bot said: "That's a smart instinct. What kind of role are you in?"
  STT transcribed user as: `"Which means more when you use Right. That's a smart mistake"`
- Bot said: "What kind of role are you in right now?"
  STT transcribed user as: `"What kind of rule I"`

**Impact:** LLM receives bot's own words as user input, creating confused conversations. Bot thinks user is repeating its questions.

**Ask:** Echo cancellation in STT pipeline, ability to pass reference audio (bot's TTS output) for filtering, or a telephony mode flag where echo is expected.

---

### Issue 3: TTS Voice Clarity — Users Reporting "Voice is Breaking" (CRITICAL)

Users explicitly tell the bot they can't hear clearly. TTS audio quality degrades during calls.

| Contact | Phone | Duration | User Complaint | Recording |
|---------|-------|----------|---------------|-----------|
| Anurag | +916393633008 | 70s | "The voice is not clear" (said twice) | [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/d0b90019-f7a6-4342-a794-b7a66b1ae9b4.mp3) |
| PRASHANTH | +919886311874 | 109s | "I can't hear you. Please do it." | [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/4295434d-d51b-4d97-b5ba-6a9fe81040dd.mp3) |
| Veerendra | +919970096043 | 146s | "Your voice is breaking a bit" | [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/6e55d197-28de-4744-a314-4cc52378f33e.mp3) |
| Santhosh | +917036723647 | 158s | "Voice is getting cut in between" | [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/35e868fb-d288-4001-b5a4-573336d36f73.mp3) |
| P T | +918590011768 | 91s | "You are not audible to me" | [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/ffb85858-3931-47e7-ade8-143bfc042190.mp3) |
| Gopi | +918124505936 | 151s | "Your voice is so stuck" | [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/e068cbce-fee3-41b0-abd7-1c634bb3f4a5.mp3) |

**Context:** All using bulbul:v3, Simran voice, en-IN. Quality seems fine at start but degrades mid-call.

**Scale of the problem:** Our red flag system detected **173 audio_failure events** across 14 days of production calls. Additional user quotes from flagged calls:

| Contact | User's Exact Words | Recording |
|---------|-------------------|-----------|
| Vedavathi (+919908206476) | "I'm not able to hear your voice. I'm getting so much gap for every word, I'm not able to hear you." | [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/2d5e942e-5e77-46bb-bf5c-1b300df5006b.mp3) |
| Neetu (+919515788390) | "Your voice is still breaking." | [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/ed509903-d669-465f-9a41-267a2d7b02b2.mp3) |
| Tanvi (+919560446849) | "I can't hear you." | [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/f33b03bc-6575-468d-8024-6d368a6592ae.mp3) |

Vedavathi's quote perfectly describes the inter-phrase gap problem: *"so much gap for every word"*.

**Ask:** Is there known quality degradation on long TTS streaming sessions? Can we get diagnostic data per session?

---

### Issue 4: Complete STT Failure — Zero Transcripts (CRITICAL)

**Call:** Smita (+919422521813) | 105s | Language: en-IN
**Recording:** [Listen](https://aps1.media.plivo.com/v1/Account/MAYME0YWZKODUWMWJINJ/Recording/48998289-3d4f-4001-93de-a3f00657c17b.mp3)

105 seconds of call with **zero transcript turns**. Recording confirms user spoke but Sarvam returned nothing.

Similarly affected:
- Preeti (+918977919651, 123s, 0 turns) — [Listen](https://aps1.media.plivo.com/v1/Account/MAYME0YWZKODUWMWJINJ/Recording/df15a4c0-0911-481d-a46c-5e0c5d5a280e.mp3)
- Sindhuri (+917799533633, 52s, 0 turns) — [Listen](https://aps1.media.plivo.com/v1/Account/MAYME0YWZKODUWMWJINJ/Recording/a8057e80-d8bc-4d9b-8c52-6e421056aed6.mp3)

**Impact:** Three calls with complete STT failure — users spoke but the bot never heard them.

---

### Issue 5: Transcript Drops — END_SPEECH with No Output (HIGH)

**Total:** 31 timeout events across 6 audited calls

| Call ID | Contact | Duration | Timeout Events | % Speech Lost |
|---------|---------|----------|---------------|---------------|
| a55b8d9f | Dinesh | 137s | **13** | ~31% |
| ed4bd290 | Pramoth | 126s | **10** | ~24% |
| 24c2549b | Santhosh | 43s | 3 | ~17% |
| 041e5416 | Dinesh | 19s | 2 | ~33% |
| 9aeef8be | Yashwanth | 25s | 2 | ~40% |
| c7a422ed | Naveen | 11s | 1 | ~33% |

Sarvam's server-side VAD fires `END_SPEECH` indicating speech detected, but ASR returns no transcript. Our system logs this as `sarvam_stt_end_speech_timeout`.

**Impact:** Bot goes silent, user thinks connection dropped. Silence watchdog fires "Hello? Can you hear me?" after 12.8s.

---

### Issue 6: Speech Fragmentation (HIGH)

Sarvam's server-side VAD splits continuous speech into multiple small transcript segments.

**English example — Keerthi (+916309454017, 197s, en-IN):**
**Recording:** [Listen](https://aps1.media.plivo.com/v1/Account/MAMDLMNDE3MMUTM2QYZC/Recording/3169ac03-303f-43c9-b3ad-a4c3ed5ebfc0.mp3)

User's single thought split across 3 turns:
```
User turn 9:  "Hmm."
User turn 10: "mainly"
User turn 11: "Nana Nani."   ← garbled hallucination
```

Later:
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

English transcribed as Kannada:
```
User turn 7:  "ಓಕೆ."                    ← user said "okay", transcribed as Kannada
User turn 17: "ಮೊಬೈಲ್ ನಂಬರ್ ಐ ಗಾಟ್."    ← "mobile number I got" in Kannada script
```

Word hallucination:
```
User turn 13: "Massage"    ← user said "message"
```

**Pattern:** Fragmentation scales with call length. Short calls (11-25s) had zero. Calls > 120s had 4-5 instances each. Affects both English and Tamil equally.

**Impact:** LLM sees fragments as complete responses, makes wrong judgments, ends calls prematurely.

---

### Issue 7: Language Misidentification (MEDIUM)

**Call:** Animesh (+919609775259) | 45s | language=unknown
**Recording:** [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/e13346f2-ff42-4084-a44b-d23750ca487c.mp3)

Auto-detect mode misidentified English as:
- Hindi: `"लोग के नाम है।"` (from English speech)
- Bengali: `"হ্যাঁ হ্যাঁ স্পিকিং ইংলিশ ও হবে না।"` (from English speech)

Also observed in en-IN mode (Harini's call): English transcribed as Kannada script despite language explicitly set to `en-IN`.

Earlier batches (Mar 5): STT output contained Amharic, Russian, French from English/Hindi speakers.

**Ask:** Can we lock STT to en-IN + hi-IN only? Confidence scores to detect low-confidence transcriptions?

---

### Issue 8: STT Hallucinations — Phantom Words (MEDIUM)

**Call:** Animesh (+919609775259) | 45s
**Recording:** [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/779c4d16-34b1-417e-aab4-aa157009e939.mp3)

Sarvam transcribed hesitation sounds as:
- `"Thank you."` — user was thinking, not saying "thank you"
- `"Bye."` — user was mid-thought, not saying goodbye

**Impact:** LLM interpreted "Thank you"/"Bye" as conversation-ending signals, hung up prematurely.

---

### Issue 9: STT WebSocket Connection Dropping (MEDIUM)

STT WebSocket closes after ~60 seconds of inactivity. If user is listening to a long bot response, the WebSocket dies silently. After that, bot hears nothing.

**Evidence:** "Bot goes silent" rate was 23.9% in Mar 7-9 batches.

**Workaround applied:** WebSocket keepalive pings every 15-20 seconds.

**Ask:** What is the actual WebSocket idle timeout? Is keepalive ping sufficient, or must we send audio frames? Can timeout be configured for telephony (30-60s silences are normal)?

---

### Issue 10: Concurrency Rate Limits Under Load (MEDIUM)

When firing 50+ concurrent calls, some get no STT response.

**Ask:** What are the current concurrency limits? What tier is needed for 100+ concurrent calls?

---

## Part 2: STT Issues — Tamil/Regional

### Issue 11: Repetition Hallucination (CRITICAL)

**Call:** Santhosh (+919176753253) | 43s | Tamil
**Recording:** [Listen](https://aps1.media.plivo.com/v1/Account/MAYJNIZJDLYZUTMGJLNS/Recording/158053c9-bc53-4677-8e5c-2bc9ba5bafa2.mp3)

Sarvam produced "ok" repeated **126 times** from a single short utterance. The STT decoder entered a runaway repetition loop.

---

### Issue 12: Garbled Tamil Transcription (MEDIUM)

Multiple calls produced syntactically broken Tamil:
- `"நீ அப்ப நீ ட்ரீக் ஆக."` — meaningless
- `"நீ காலேஜ் குட்."` — "You college good" — nonsensical
- `"ஏய் கல்புற்றா, ஹலோ."` — garbled
- `"ஹெல்த்தியாக்குறாப்புல அவரு."` — partially intelligible but mangled

STT appears to confuse phonemes in colloquial/spoken Tamil vs. formal written Tamil.

---

## Part 3: TTS Issues (bulbul:v3)

### Audio Quality Analysis — 5 Recordings

| Recording | Duration | Silence % | Gaps > 1.5s | Gaps > 3s | Worst Gap | Recording |
|-----------|----------|-----------|-------------|-----------|-----------|-----------|
| **Falguni** | 55s | **71.1%** | 8 | 3 | **14.1s** | [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/99ec9c6e-ec8c-4d65-85a4-5aa154fabf05.mp3) |
| **Dinesh** | 136s | **47.2%** | 20 | 3 | 4.3s | [Listen](https://aps1.media.plivo.com/v1/Account/MAYJNIZJDLYZUTMGJLNS/Recording/dc9faa97-2156-43f7-a4c5-d4f7deed26f8.mp3) |
| Pramoth | 126s | 44.5% | 19 | 3 | 4.0s | [Listen](https://aps1.media.plivo.com/v1/Account/MAYJNIZJDLYZUTMGJLNS/Recording/0c625466-fbd8-42bd-b385-f2b9c8da94cf.mp3) |
| SNA | 138s | 41.2% | 18 | 3 | 6.9s | [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/b8e1a810-68fb-4c89-9623-60d6428e4a80.mp3) |
| Sahil | 195s | 23.5% | 12 | 2 | 4.7s | [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/217413ae-4db7-4a5f-bbfd-b4c88b102aae.mp3) |

**Methodology:** FFmpeg silence detection at -40dB threshold, gaps > 0.5s counted. Stereo recordings (left=bot, right=user).

### Issue 13: Catastrophic TTS Stall (CRITICAL)

**Call:** Falguni | 55s | 71.1% silence
**Recording:** [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/99ec9c6e-ec8c-4d65-85a4-5aa154fabf05.mp3)

14.1-second continuous silence at 0:36-0:50. TTS completely stalled. Additional gaps: 5.9s at 0:06, 5.5s at 0:14.

### Issue 14: Pervasive Inter-Phrase Audio Gaps (HIGH)

Average silence: **45.5%** across all 5 recordings. Every recording has at least 2 gaps > 3 seconds.

**Per-call breakdown:**
- **Falguni** — 14.1s at 0:36, 5.9s at 0:06, 5.5s at 0:14
- **SNA** — 6.9s at 0:21, 4.4s at 0:52, 3.9s at 0:41
- **Dinesh** — 40 gaps, one every 3.4s. Worst: 4.3s at 0:54
- **Pramoth** — 3.3s at 1:37, 3.1s at 0:10
- **Sahil** — 4.7s at 2:08 (best quality at 23.5% silence, but clips at 0.0 dB)

**Live-debugged example — Animesh (+919609775259, 153s):**
**Recording:** [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/e13346f2-ff42-4084-a44b-d23750ca487c.mp3)

We did detailed audio analysis on this call with FFmpeg silence detection:
- **36% of the call is silence** (55s of silence in 153s)
- **13 gaps > 2 seconds**, worst being **10.3 seconds** at 1:51-2:01
- **5.1 second gap** at 1:23-1:28
- Gaps are **evenly distributed** throughout the entire call — not just at the start

We also captured per-turn TTS latency from our pipeline logs:

| Turn | TTS Time-to-First-Byte | End-to-End Latency |
|------|----------------------|-------------------|
| Turn 9 | **3,850ms** | 4,537ms |
| Turn 11 | 964ms | 1,675ms |
| Turn 12 | 955ms | 958ms |
| Turn 13 | 795ms | 1,482ms |

Turn 9 had a 3.85-second wait before first audio — the user heard nearly 4 seconds of silence mid-conversation. The bot's response was: *"Right right, the problem with self-learning is you end up watching more than doing..."* — a longer sentence where the first TTS chunk took 3.85s to synthesize.

**Additional test calls with audible breaking:**
- [80s call](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/779c4d16-34b1-417e-aab4-aa157009e939.mp3) — mid-sentence audio drops throughout, STT hallucination "Thank you"
- [154s call](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/8fa2ff8f-d4e1-48aa-b96a-f32e9ca7ddd9.mp3) — 22% silence, 11-second STT gap from Deepgram latency spike

**Ask:** Expected TTFB for 30-char chunk? Can `min_buffer_size` go below 30? Is progressive audio delivery possible? Does requesting 16kHz (non-native) add latency vs 24kHz?

### Issue 15: Silent/Noisy Audio Tails (MEDIUM)

bulbul:v3 emits long near-silent or noisy tails after speech finishes. We built a custom `TTSTailTrim` processor (RMS < 90, max_amp < 300, drops after 900ms) to handle this.

Without trim: 200ms-2s of dead noise after every utterance.
With trim: Occasionally clips legitimate quiet endings.

### Issue 16: Volume Inconsistency (LOW)

- Falguni: -30.9 dB mean (very quiet)
- Sahil: 0.0 dB max (clipping/distortion)
- Range: 8 dB spread across calls

---

## Part 4: Configuration Context

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

Full architecture details in companion document: `sarvam-architecture-external.md`

---

## Additional Flagged Calls

| Contact | Phone | Duration | Issue | Recording |
|---------|-------|----------|-------|-----------|
| SOUMYA | +917008322800 | 126s | User detected AI, partly due to audio quality | [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/98a9f9ea-2b87-48b6-afa3-4652cf9f2477.mp3) |
| Supratim | +918076019909 | 70s | User rejected AI call due to audio quality | [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/a04bec4a-bbf0-495e-b19c-d9d7e93799b1.mp3) |
| Sahil | +919817562070 | 195s | STT couldn't handle Hindi-English mix | [Listen](https://aps1.media.plivo.com/v1/Account/MAOWZHNJRJMTKWNZVKZJ/Recording/217413ae-4db7-4a5f-bbfd-b4c88b102aae.mp3) |
