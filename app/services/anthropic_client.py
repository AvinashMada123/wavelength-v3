"""Claude API wrapper for sequence copywriting and prompt testing."""

import re
import time

import anthropic
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)

MODEL_MAP = {
    "claude-sonnet": "claude-sonnet-4-20250514",
    "claude-haiku": "claude-haiku-4-5-20251001",
    # New IDs used by flow builder AI nodes
    "claude-sonnet-4-6": "claude-sonnet-4-20250514",
    "claude-haiku-4-5": "claude-haiku-4-5-20251001",
}

COST_PER_1M_INPUT = {"claude-sonnet": 3.00, "claude-haiku": 0.80}
COST_PER_1M_OUTPUT = {"claude-sonnet": 15.00, "claude-haiku": 4.00}


def _interpolate_variables(prompt: str, variables: dict) -> str:
    """Replace {{variable}} placeholders with values. Missing vars left as-is."""
    def replacer(match):
        key = match.group(1).strip()
        return str(variables[key]) if key in variables else match.group(0)
    return re.sub(r"\{\{(\s*\w+\s*)\}\}", replacer, prompt)


def extract_variable_names(prompt: str) -> set[str]:
    """Extract unique variable names from a prompt template."""
    return {m.strip() for m in re.findall(r"\{\{(\s*\w+\s*)\}\}", prompt)}


async def generate_content(
    prompt: str,
    variables: dict,
    model: str = "claude-sonnet",
    max_tokens: int = 300,
    org_id: str | None = None,
    reference: str | None = None,
) -> str:
    """Interpolate variables and call Claude. Returns generated text.
    If org_id provided, bills the AI usage to the org's credit balance."""
    filled_prompt = _interpolate_variables(prompt, variables)
    model_id = MODEL_MAP.get(model, MODEL_MAP["claude-sonnet"])

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    try:
        response = await client.messages.create(
            model=model_id,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": filled_prompt}],
        )
        if org_id:
            try:
                from app.database import get_db_session
                from app.services.billing import bill_ai_usage
                import uuid as _uuid
                async with get_db_session() as db:
                    await bill_ai_usage(
                        db,
                        org_id=_uuid.UUID(org_id) if isinstance(org_id, str) else org_id,
                        tokens_used=response.usage.input_tokens + response.usage.output_tokens,
                        model=model,
                        reference=reference or "sequence_content",
                    )
            except Exception:
                logger.warning("ai_billing_failed", org_id=org_id)

        return response.content[0].text.strip()
    except Exception:
        logger.exception("anthropic_generation_failed", model=model_id)
        raise
    finally:
        await client.close()


async def test_prompt(
    prompt: str,
    sample_variables: dict,
    model: str = "claude-sonnet",
    max_tokens: int = 300,
) -> dict:
    """Generate content and return metadata for the prompt test UI."""
    filled_prompt = _interpolate_variables(prompt, sample_variables)
    model_id = MODEL_MAP.get(model, MODEL_MAP["claude-sonnet"])

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    try:
        start = time.monotonic()
        response = await client.messages.create(
            model=model_id,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": filled_prompt}],
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        input_cost = (input_tokens / 1_000_000) * COST_PER_1M_INPUT.get(model, 3.0)
        output_cost = (output_tokens / 1_000_000) * COST_PER_1M_OUTPUT.get(model, 15.0)

        return {
            "generated_content": response.content[0].text.strip(),
            "tokens_used": input_tokens + output_tokens,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": latency_ms,
            "cost_estimate": round(input_cost + output_cost, 6),
            "model": model_id,
            "filled_prompt": filled_prompt,
        }
    except Exception:
        logger.exception("anthropic_test_prompt_failed", model=model_id)
        raise
    finally:
        await client.close()
