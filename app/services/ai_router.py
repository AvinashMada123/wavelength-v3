"""Unified AI content generation router.

Routes generation requests to Anthropic or Google based on model prefix.
Used by flow engine action nodes for AI-generated content.
"""
import logging
import re

from app.services import anthropic_client

logger = logging.getLogger(__name__)

# Supported models and their providers
SUPPORTED_MODELS = {
    "gemini-2.5-flash": "google",
    "gemini-2.5-pro": "google",
    "gemini-2.0-flash": "google",
    "claude-sonnet-4-6": "anthropic",
    "claude-haiku-4-5": "anthropic",
}

# Display names for the frontend dropdown
MODEL_DISPLAY_NAMES = {
    "gemini-2.5-flash": "Gemini 2.5 Flash",
    "gemini-2.5-pro": "Gemini 2.5 Pro",
    "gemini-2.0-flash": "Gemini 2.0 Flash",
    "claude-sonnet-4-6": "Claude Sonnet 4.6",
    "claude-haiku-4-5": "Claude Haiku 4.5",
}

DEFAULT_MODEL = "gemini-2.5-flash"


def resolve_provider(model: str) -> str:
    """Determine which provider handles this model."""
    if model in SUPPORTED_MODELS:
        return SUPPORTED_MODELS[model]
    raise ValueError(f"Unknown model: {model}. Supported: {list(SUPPORTED_MODELS.keys())}")


def _interpolate_variables(prompt: str, variables: dict) -> str:
    """Replace {{var}} placeholders with values from variables dict."""
    def replace_match(match):
        key = match.group(1).strip()
        return str(variables.get(key, match.group(0)))
    return re.sub(r"\{\{(\s*\w+\s*)\}\}", replace_match, prompt)


async def generate_content(
    prompt: str,
    variables: dict,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 300,
    org_id: str | None = None,
    reference: str | None = None,
) -> str:
    """Generate AI content, routing to the correct provider.

    Args:
        prompt: Prompt template with {{variable}} placeholders.
        variables: Dict of variable values to interpolate.
        model: Model ID (e.g., "gemini-2.5-flash", "claude-sonnet-4-6").
        max_tokens: Max output tokens.
        org_id: For billing/tracking.
        reference: Context reference string.

    Returns: Generated text content.
    """
    provider = resolve_provider(model)

    if provider == "anthropic":
        return await anthropic_client.generate_content(
            prompt=prompt,
            variables=variables,
            model=model,
            max_tokens=max_tokens,
            org_id=org_id,
            reference=reference,
        )
    elif provider == "google":
        return await _generate_with_google(
            prompt=prompt,
            variables=variables,
            model=model,
            max_tokens=max_tokens,
        )
    else:
        raise ValueError(f"Unsupported provider: {provider}")


async def _generate_with_google(
    prompt: str,
    variables: dict,
    model: str,
    max_tokens: int = 300,
) -> str:
    """Generate content using Google GenAI (Vertex AI).

    Uses the same pattern as call_analyzer.py's _gemini_call().
    """
    from google import genai
    from google.genai.types import GenerateContentConfig
    from app.config import settings

    interpolated_prompt = _interpolate_variables(prompt, variables)

    # Must pass project + location — same pattern as call_analyzer.py
    client = genai.Client(
        vertexai=True,
        project=settings.GOOGLE_CLOUD_PROJECT,
        location=settings.VERTEX_AI_LOCATION,
    )
    response = await client.aio.models.generate_content(
        model=model,
        contents=interpolated_prompt,
        config=GenerateContentConfig(
            max_output_tokens=max_tokens,
            temperature=0.7,
        ),
    )

    return response.text
