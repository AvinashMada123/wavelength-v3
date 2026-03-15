"""
Post-call analysis service — structured LLM analysis of call transcripts.

Extracts: summary, sentiment, call score, lead temperature, objections,
buying signals, key topics, recommended next action, and talk ratio.

Uses Vertex AI Gemini with retry on 429/503 errors and a concurrency
semaphore to protect against quota exhaustion during batch completions.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)

# Limit concurrent analysis tasks to prevent 429s
_ANALYSIS_SEMAPHORE = asyncio.Semaphore(5)


@dataclass
class Objection:
    category: str
    text: str
    resolved: bool = False


@dataclass
class CallAnalysisResult:
    summary: str | None = None
    sentiment: str | None = None  # positive / neutral / negative
    sentiment_score: int | None = None  # 1-10
    call_score: int | None = None  # 0-100
    lead_temperature: str | None = None  # hot / warm / cold / dead
    objections: list[Objection] = field(default_factory=list)
    buying_signals: list[str] = field(default_factory=list)
    key_topics: list[str] = field(default_factory=list)
    recommended_next_action: str | None = None
    talk_ratio: dict[str, float] = field(default_factory=dict)  # bot_pct, lead_pct
    input_tokens: int = 0
    output_tokens: int = 0


class CallAnalysisService:
    """Structured post-call analysis using Gemini."""

    async def analyze(
        self,
        transcript: list[dict],
        bot_config: dict | None = None,
        call_sid: str | None = None,
    ) -> CallAnalysisResult | None:
        """
        Analyze a call transcript and return structured insights.

        Args:
            transcript: List of {role, content} message dicts.
            bot_config: Optional bot configuration dict for context.
            call_sid: Optional call SID for logging.

        Returns:
            CallAnalysisResult or None on complete failure.
        """
        if not transcript:
            logger.info("call_analysis_skipped_empty_transcript", call_sid=call_sid)
            return CallAnalysisResult()

        # Compute talk ratio from transcript word counts
        talk_ratio = self._compute_talk_ratio(transcript)

        # Build conversation text
        conv_text = "\n".join(
            f"{t['role'].upper()}: {t['content']}" for t in transcript
        )

        # Build context from bot config
        context_lines = ""
        if bot_config:
            agent_name = bot_config.get("agent_name", "AI Agent")
            company_name = bot_config.get("company_name", "")
            if company_name:
                context_lines = f"**Agent:** {agent_name} from {company_name}\n"
            else:
                context_lines = f"**Agent:** {agent_name}\n"

        prompt = (
            "You are an expert sales call analyst. Analyze the following phone call "
            "transcript and extract structured insights.\n\n"
            f"{context_lines}"
            f"**Transcript:**\n{conv_text}\n\n"
            "Respond with ONLY valid JSON (no markdown, no code fences):\n"
            "{\n"
            '  "summary": "<3-5 sentence summary of the call including key outcome>",\n'
            '  "sentiment": "<positive|neutral|negative>",\n'
            '  "sentiment_score": <1-10, where 1=very negative, 10=very positive>,\n'
            '  "call_score": <0-100, overall call quality/effectiveness score>,\n'
            '  "lead_temperature": "<hot|warm|cold|dead>",\n'
            '  "objections": [\n'
            '    {"category": "<price|timing|competition|authority|need|other>", '
            '"text": "<the objection raised>", "resolved": <true|false>}\n'
            "  ],\n"
            '  "buying_signals": ["<signal 1>", "<signal 2>"],\n'
            '  "key_topics": ["<topic 1>", "<topic 2>"],\n'
            '  "recommended_next_action": "<specific next step for the sales team>"\n'
            "}"
        )

        async with _ANALYSIS_SEMAPHORE:
            try:
                response = await self._gemini_call(
                    prompt, temperature=0.2, call_sid=call_sid
                )
            except Exception as e:
                logger.error(
                    "call_analysis_gemini_failed",
                    call_sid=call_sid,
                    error=str(e)[:200],
                )
                return None

        result_dict = self._parse_json_response(response.text)
        if not result_dict:
            logger.warning("call_analysis_parse_failed", call_sid=call_sid)
            return None

        # Extract token usage
        token_info = self._extract_token_usage(response)

        # Validate and clamp values
        sentiment = result_dict.get("sentiment")
        if sentiment not in ("positive", "neutral", "negative"):
            sentiment = "neutral"

        sentiment_score = result_dict.get("sentiment_score")
        if isinstance(sentiment_score, (int, float)):
            sentiment_score = max(1, min(10, int(sentiment_score)))
        else:
            sentiment_score = None

        call_score = result_dict.get("call_score")
        if isinstance(call_score, (int, float)):
            call_score = max(0, min(100, int(call_score)))
        else:
            call_score = None

        lead_temp = result_dict.get("lead_temperature")
        if lead_temp not in ("hot", "warm", "cold", "dead"):
            lead_temp = "cold"

        # Parse objections
        objections = []
        for obj in result_dict.get("objections", []) or []:
            if isinstance(obj, dict) and obj.get("text"):
                objections.append(Objection(
                    category=obj.get("category", "other"),
                    text=obj["text"],
                    resolved=bool(obj.get("resolved", False)),
                ))

        # Parse lists safely
        buying_signals = [
            str(s) for s in (result_dict.get("buying_signals") or [])
            if s
        ]
        key_topics = [
            str(t) for t in (result_dict.get("key_topics") or [])
            if t
        ]

        analysis = CallAnalysisResult(
            summary=result_dict.get("summary"),
            sentiment=sentiment,
            sentiment_score=sentiment_score,
            call_score=call_score,
            lead_temperature=lead_temp,
            objections=objections,
            buying_signals=buying_signals,
            key_topics=key_topics,
            recommended_next_action=result_dict.get("recommended_next_action"),
            talk_ratio=talk_ratio,
            input_tokens=token_info["input_tokens"],
            output_tokens=token_info["output_tokens"],
        )

        logger.info(
            "call_analysis_complete",
            call_sid=call_sid,
            sentiment=analysis.sentiment,
            call_score=analysis.call_score,
            lead_temperature=analysis.lead_temperature,
            objection_count=len(analysis.objections),
            buying_signal_count=len(analysis.buying_signals),
            input_tokens=analysis.input_tokens,
            output_tokens=analysis.output_tokens,
        )

        return analysis

    def _compute_talk_ratio(self, transcript: list[dict]) -> dict[str, float]:
        """Compute bot vs lead talk ratio from word counts."""
        bot_words = 0
        lead_words = 0
        for msg in transcript:
            word_count = len((msg.get("content") or "").split())
            role = (msg.get("role") or "").lower()
            if role in ("assistant", "bot", "agent"):
                bot_words += word_count
            elif role in ("user", "lead", "human"):
                lead_words += word_count

        total = bot_words + lead_words
        if total == 0:
            return {"bot_pct": 50.0, "lead_pct": 50.0}

        return {
            "bot_pct": round(bot_words / total * 100, 1),
            "lead_pct": round(lead_words / total * 100, 1),
        }

    async def _gemini_call(
        self,
        prompt: str,
        temperature: float,
        call_sid: str | None,
        max_retries: int = 3,
    ):
        """Make a Vertex AI Gemini call with retry on 429/503."""
        from google import genai
        from app.config import settings

        for attempt in range(max_retries):
            try:
                client = genai.Client(
                    vertexai=True,
                    project=settings.GOOGLE_CLOUD_PROJECT,
                    location=settings.VERTEX_AI_LOCATION,
                )
                response = await client.aio.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=genai.types.GenerateContentConfig(
                        max_output_tokens=1024,
                        temperature=temperature,
                        thinking_config=genai.types.ThinkingConfig(thinking_budget=0),
                    ),
                )
                return response
            except Exception as e:
                error_str = str(e)
                if attempt < max_retries - 1 and ("429" in error_str or "503" in error_str):
                    wait = 2 ** attempt
                    logger.warning(
                        "call_analysis_gemini_retry",
                        call_sid=call_sid,
                        attempt=attempt + 1,
                        wait_secs=wait,
                        error=error_str[:200],
                    )
                    await asyncio.sleep(wait)
                    continue
                raise

    def _parse_json_response(self, text: str) -> dict:
        """Parse JSON from Gemini response, handling markdown code blocks and truncation."""
        text = text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to extract JSON object from the text
            match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            # Try to repair truncated JSON by closing open strings/braces
            repaired = text.rstrip()
            if not repaired.endswith("}"):
                if repaired.count('"') % 2 == 1:
                    repaired += '"'
                repaired += "}"
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                logger.warning("call_analysis_json_parse_failed", preview=text[:500])
                return {}

    def _extract_token_usage(self, response) -> dict:
        """Extract input/output token counts from Gemini response."""
        try:
            usage = getattr(response, "usage_metadata", None)
            if usage:
                return {
                    "input_tokens": getattr(usage, "prompt_token_count", 0) or 0,
                    "output_tokens": getattr(usage, "candidates_token_count", 0) or 0,
                }
        except Exception:
            pass
        return {"input_tokens": 0, "output_tokens": 0}
