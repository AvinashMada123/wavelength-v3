"""
Goal-aware post-call analysis engine.

Two parallel Gemini calls for accuracy:
- Call 1: Goal outcome + summary (narrative understanding, temp=0.3)
- Call 2: Red flags + captured data (structured extraction, temp=0.1)

Includes:
- asyncio.Semaphore to limit concurrent analyses (protects against 429s)
- Retry with exponential backoff on 429/503
- Red flag merge (realtime + post-call, deduped by flag_id)
- Fallback to generic summary when no goal_config
"""

from __future__ import annotations

import asyncio
import json
import re

import structlog

from app.models.schemas import CallAnalysis, GoalConfig, RedFlagDetection

logger = structlog.get_logger(__name__)

# Limit concurrent analysis tasks to prevent 429s during batch campaign endings
_ANALYSIS_SEMAPHORE = asyncio.Semaphore(5)

_INTEREST_RE = re.compile(r"INTEREST:\s*(high|medium|low)", re.IGNORECASE)


class CallAnalyzer:
    """Goal-aware post-call analysis. Two LLM calls for accuracy."""

    async def analyze(
        self,
        transcript: list[dict],
        goal_config: GoalConfig | dict | None,
        system_prompt: str,
        realtime_red_flags: list[dict] | None = None,
        call_sid: str | None = None,
        thinking_enabled: bool = False,
    ) -> CallAnalysis:
        """
        Analyze a call transcript against the bot's goal configuration.

        When goal_config is None, falls back to generic summary + interest.
        """
        self._thinking_enabled = thinking_enabled
        if not transcript:
            return CallAnalysis()

        # Parse goal_config from str/dict into GoalConfig
        parsed_config: GoalConfig | None = None
        if goal_config is not None:
            if isinstance(goal_config, str):
                goal_config = json.loads(goal_config)
            if isinstance(goal_config, dict):
                parsed_config = GoalConfig(**goal_config)
            else:
                parsed_config = goal_config

        if parsed_config is None:
            return await self._fallback_generic(transcript, call_sid)

        async with _ANALYSIS_SEMAPHORE:
            outcome_result, extraction_result = await asyncio.gather(
                self._analyze_outcome(transcript, parsed_config, system_prompt, call_sid),
                self._extract_structured_data(transcript, parsed_config, call_sid),
                return_exceptions=True,
            )

        # Handle errors from either call
        if isinstance(outcome_result, Exception):
            logger.error("analyze_outcome_failed", call_sid=call_sid, error=str(outcome_result))
            outcome_result = {"goal_outcome": None, "summary": None, "interest_level": None,
                              "sentiment": None, "sentiment_score": None,
                              "lead_temperature": None, "buying_signals": None,
                              "input_tokens": 0, "output_tokens": 0}
        if isinstance(extraction_result, Exception):
            logger.error("extract_structured_failed", call_sid=call_sid, error=str(extraction_result))
            extraction_result = {"red_flags": [], "captured_data": {}, "objections": None,
                                 "input_tokens": 0, "output_tokens": 0}

        # Merge real-time + post-call red flags (dedupe by flag_id)
        merged_flags = self._merge_red_flags(
            realtime_flags=realtime_red_flags or [],
            postcard_flags=extraction_result.get("red_flags", []),
        )

        # Log cost
        total_input = outcome_result.get("input_tokens", 0) + extraction_result.get("input_tokens", 0)
        total_output = outcome_result.get("output_tokens", 0) + extraction_result.get("output_tokens", 0)
        logger.info(
            "analysis_cost",
            call_sid=call_sid,
            call_1_input_tokens=outcome_result.get("input_tokens", 0),
            call_1_output_tokens=outcome_result.get("output_tokens", 0),
            call_2_input_tokens=extraction_result.get("input_tokens", 0),
            call_2_output_tokens=extraction_result.get("output_tokens", 0),
            total_input_tokens=total_input,
            total_output_tokens=total_output,
        )

        # Validate sentiment
        sentiment = outcome_result.get("sentiment")
        if sentiment not in ("positive", "neutral", "negative"):
            sentiment = None

        # Validate sentiment_score
        sentiment_score = outcome_result.get("sentiment_score")
        if isinstance(sentiment_score, (int, float)):
            sentiment_score = max(1, min(10, int(sentiment_score)))
        else:
            sentiment_score = None

        # Validate lead_temperature
        lead_temperature = outcome_result.get("lead_temperature")
        if lead_temperature not in ("hot", "warm", "cold", "dead"):
            lead_temperature = None

        # Parse buying_signals
        buying_signals = outcome_result.get("buying_signals")
        if isinstance(buying_signals, list):
            buying_signals = [str(s) for s in buying_signals if s]
        else:
            buying_signals = None

        # Parse objections from extraction call
        raw_objections = extraction_result.get("objections")
        objections = None
        if isinstance(raw_objections, list):
            objections = []
            for obj in raw_objections:
                if isinstance(obj, dict) and obj.get("text"):
                    objections.append({
                        "category": obj.get("category", "other"),
                        "text": obj["text"],
                        "resolved": bool(obj.get("resolved", False)),
                    })

        return CallAnalysis(
            goal_outcome=outcome_result.get("goal_outcome"),
            summary=outcome_result.get("summary"),
            interest_level=outcome_result.get("interest_level"),
            red_flags=[RedFlagDetection(**rf) for rf in merged_flags],
            captured_data=extraction_result.get("captured_data", {}),
            sentiment=sentiment,
            sentiment_score=sentiment_score,
            lead_temperature=lead_temperature,
            objections=objections,
            buying_signals=buying_signals,
            input_tokens=total_input or None,
            output_tokens=total_output or None,
        )

    async def _analyze_outcome(
        self,
        transcript: list[dict],
        goal_config: GoalConfig,
        system_prompt: str,
        call_sid: str | None,
    ) -> dict:
        """Call 1: Goal outcome + summary (narrative understanding)."""
        criteria_desc = "\n".join(
            f"- \"{c.id}\": {c.label}" + (" (PRIMARY)" if c.is_primary else "")
            for c in goal_config.success_criteria
        )

        conv_text = "\n".join(
            f"{t['role'].upper()}: {t['content']}" for t in transcript
        )

        prompt = (
            f"You are analyzing a phone call made by an AI agent.\n\n"
            f"**Bot's Goal:** {goal_config.goal_description}\n\n"
            f"**Possible Outcomes (pick one ID):**\n{criteria_desc}\n\n"
            f"**Transcript:**\n{conv_text}\n\n"
            f"Analyze the conversation and respond with ONLY valid JSON (no markdown):\n"
            f'{{"goal_outcome": "<id from the list above, or \\"none\\" if no outcome was reached>",'
            f' "summary": "<2-3 sentence summary contextualized to the goal>",'
            f' "interest_level": "<high|medium|low>",'
            f' "sentiment": "<positive|neutral|negative>",'
            f' "sentiment_score": <1-10 where 1=very negative 10=very positive>,'
            f' "lead_temperature": "<hot|warm|cold|dead>",'
            f' "buying_signals": ["<specific buying signal quotes or phrases from the lead>"]}}'
        )

        response = await self._gemini_call(prompt, temperature=0.3, call_sid=call_sid)
        result = self._parse_json_response(response.text)

        # Extract token usage
        token_info = self._extract_token_usage(response)
        result["input_tokens"] = token_info["input_tokens"]
        result["output_tokens"] = token_info["output_tokens"]

        # Validate goal_outcome is a valid criterion ID or "none"
        valid_ids = {c.id for c in goal_config.success_criteria} | {"none"}
        raw_outcome = result.get("goal_outcome")
        if raw_outcome is None or raw_outcome not in valid_ids:
            logger.warning(
                "invalid_goal_outcome",
                call_sid=call_sid,
                got=raw_outcome,
                valid=list(valid_ids),
            )
            result["goal_outcome"] = "none"

        return result

    async def _extract_structured_data(
        self,
        transcript: list[dict],
        goal_config: GoalConfig,
        call_sid: str | None,
    ) -> dict:
        """Call 2: Red flags + captured data (structured extraction)."""
        conv_text = "\n".join(
            f"{t['role'].upper()}: {t['content']}" for t in transcript
        )

        # Build red flag descriptions (post_call only — realtime handled by CallGuard)
        post_call_flags = [rf for rf in goal_config.red_flags if rf.detect_in == "post_call"]
        flags_desc = ""
        if post_call_flags:
            flag_lines = "\n".join(
                f'- "{rf.id}" ({rf.severity}): {rf.label}'
                for rf in post_call_flags
            )
            flags_desc = (
                f"**Red Flags to Check:**\n{flag_lines}\n\n"
                f"For each detected red flag, include it in the red_flags array with: "
                f"id, severity, evidence (exact quote from transcript).\n\n"
            )

        # Build data capture field descriptions
        fields_desc = ""
        if goal_config.data_capture_fields:
            field_lines = []
            for f in goal_config.data_capture_fields:
                line = f'- "{f.id}": {f.label}'
                if f.description:
                    line += f" — {f.description}"
                if f.type == "enum" and f.enum_values:
                    line += f". MUST be one of: {f.enum_values}"
                elif f.type in ("integer", "float"):
                    line += f". Must be a {f.type} value."
                field_lines.append(line)
            fields_desc = (
                f"**Data to Extract:**\n" + "\n".join(field_lines) + "\n\n"
                f"For each field, extract the value from the conversation. "
                f"Use null if the information is not mentioned.\n\n"
            )

        prompt = (
            f"You are extracting structured data from a phone call transcript.\n\n"
            f"{flags_desc}"
            f"{fields_desc}"
            f"**Transcript:**\n{conv_text}\n\n"
            f"Respond with ONLY valid JSON (no markdown):\n"
            f'{{"red_flags": [{{"id": "...", "severity": "...", "evidence": "..."}}], '
            f'"captured_data": {{"field_id": "value_or_null"}}, '
            f'"objections": [{{"category": "<price|timing|competition|authority|need|other>", '
            f'"text": "<the objection raised>", "resolved": <true|false>}}]}}'
        )

        response = await self._gemini_call(prompt, temperature=0.1, call_sid=call_sid)
        result = self._parse_json_response(response.text)

        # Extract token usage
        token_info = self._extract_token_usage(response)
        result["input_tokens"] = token_info["input_tokens"]
        result["output_tokens"] = token_info["output_tokens"]

        # Validate enum field values — set invalid values to None
        for f in goal_config.data_capture_fields:
            if f.type == "enum" and f.enum_values:
                value = result.get("captured_data", {}).get(f.id)
                if value is not None and value not in f.enum_values:
                    logger.warning(
                        "invalid_enum_value_nullified",
                        call_sid=call_sid,
                        field=f.id,
                        got=value,
                        valid=f.enum_values,
                    )
                    result.setdefault("captured_data", {})[f.id] = None

        return result

    async def _fallback_generic(
        self, transcript: list[dict], call_sid: str | None
    ) -> CallAnalysis:
        """Generic summary + interest + sentiment + signals when no goal_config is set."""
        conv_text = "\n".join(
            f"{t['role'].upper()}: {t['content']}" for t in transcript
        )

        prompt = (
            "Analyze this phone conversation and respond with ONLY valid JSON (no markdown):\n"
            "{\n"
            '  "summary": "<2-3 sentence summary including key outcome>",\n'
            '  "interest_level": "<high|medium|low>",\n'
            '  "sentiment": "<positive|neutral|negative>",\n'
            '  "sentiment_score": <1-10 where 1=very negative 10=very positive>,\n'
            '  "lead_temperature": "<hot|warm|cold|dead>",\n'
            '  "objections": [{"category": "<price|timing|competition|authority|need|other>", '
            '"text": "<the objection raised>", "resolved": <true|false>}],\n'
            '  "buying_signals": ["<specific buying signal quotes or phrases>"]\n'
            "}\n\n"
            f"**Transcript:**\n{conv_text}"
        )

        async with _ANALYSIS_SEMAPHORE:
            response = await self._gemini_call(prompt, temperature=0.3, call_sid=call_sid)

        result = self._parse_json_response(response.text)

        summary = result.get("summary")
        interest_level = result.get("interest_level")
        if interest_level not in ("high", "medium", "low"):
            interest_level = None

        # Validate sentiment
        sentiment = result.get("sentiment")
        if sentiment not in ("positive", "neutral", "negative"):
            sentiment = None

        # Validate sentiment_score
        sentiment_score = result.get("sentiment_score")
        if isinstance(sentiment_score, (int, float)):
            sentiment_score = max(1, min(10, int(sentiment_score)))
        else:
            sentiment_score = None

        # Validate lead_temperature
        lead_temperature = result.get("lead_temperature")
        if lead_temperature not in ("hot", "warm", "cold", "dead"):
            lead_temperature = None

        # Parse buying_signals
        buying_signals = result.get("buying_signals")
        if isinstance(buying_signals, list):
            buying_signals = [str(s) for s in buying_signals if s]
        else:
            buying_signals = None

        # Parse objections
        raw_objections = result.get("objections")
        objections = None
        if isinstance(raw_objections, list):
            objections = []
            for obj in raw_objections:
                if isinstance(obj, dict) and obj.get("text"):
                    objections.append({
                        "category": obj.get("category", "other"),
                        "text": obj["text"],
                        "resolved": bool(obj.get("resolved", False)),
                    })

        logger.info(
            "fallback_analysis_generated",
            call_sid=call_sid,
            summary_length=len(summary) if summary else 0,
            interest_level=interest_level,
            sentiment=sentiment,
            lead_temperature=lead_temperature,
        )

        return CallAnalysis(
            summary=summary,
            interest_level=interest_level,
            sentiment=sentiment,
            sentiment_score=sentiment_score,
            lead_temperature=lead_temperature,
            objections=objections,
            buying_signals=buying_signals,
        )

    async def _gemini_call(self, prompt: str, temperature: float, call_sid: str | None, max_retries: int = 3):
        """Make a Vertex AI Gemini call with retry on 429/503."""
        from google import genai
        from app.config import settings

        thinking_config = None
        if not getattr(self, "_thinking_enabled", True):
            thinking_config = genai.types.ThinkingConfig(thinking_budget=0)

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
                        thinking_config=thinking_config,
                    ),
                )
                return response
            except Exception as e:
                error_str = str(e)
                if attempt < max_retries - 1 and ("429" in error_str or "503" in error_str):
                    wait = 2 ** attempt
                    logger.warning(
                        "gemini_retry",
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
        if not text:
            logger.error("json_parse_failed_empty_response")
            return {}
        text = text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Use balanced brace counting to extract the outermost {...} block
            extracted = self._extract_outermost_json(text)
            if extracted:
                try:
                    return json.loads(extracted)
                except json.JSONDecodeError:
                    pass
            # Try to repair truncated JSON by closing open strings/braces
            repaired = text.rstrip()
            if not repaired.endswith("}"):
                # Close any open string
                if repaired.count('"') % 2 == 1:
                    repaired += '"'
                repaired += "}"
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                logger.error("json_parse_failed", preview=text[:500])
                return {}

    @staticmethod
    def _extract_outermost_json(text: str) -> str | None:
        """Extract the outermost {...} block using balanced brace counting."""
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        in_string = False
        escape_next = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape_next:
                escape_next = False
                continue
            if ch == "\\":
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        # Unbalanced — return from start to end (let caller try to repair)
        return None

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

    def _merge_red_flags(
        self,
        realtime_flags: list[dict],
        postcard_flags: list[dict],
    ) -> list[dict]:
        """Deduplicate by flag_id. Prefer real-time (has actual turn_index).
        When same flag detected in both, keep realtime but append post-call evidence."""
        seen_ids: dict[str, int] = {}  # flag_id -> index in merged list
        merged: list[dict] = []
        for rf in realtime_flags:
            seen_ids[rf["id"]] = len(merged)
            merged.append(rf)
        for rf in postcard_flags:
            flag_id = rf.get("id")
            if flag_id in seen_ids:
                # Same flag in both — append post-call evidence to realtime entry
                idx = seen_ids[flag_id]
                post_evidence = rf.get("evidence")
                if post_evidence:
                    merged[idx]["additional_evidence"] = post_evidence
            else:
                merged.append(rf)
        return merged
