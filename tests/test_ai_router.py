# tests/test_ai_router.py
import pytest
from unittest.mock import AsyncMock, patch


def test_resolve_provider_anthropic():
    from app.services.ai_router import resolve_provider
    assert resolve_provider("claude-sonnet-4-6") == "anthropic"
    assert resolve_provider("claude-haiku-4-5") == "anthropic"


def test_resolve_provider_google():
    from app.services.ai_router import resolve_provider
    assert resolve_provider("gemini-2.5-flash") == "google"
    assert resolve_provider("gemini-2.5-pro") == "google"
    assert resolve_provider("gemini-2.0-flash") == "google"


def test_resolve_provider_unknown_raises():
    from app.services.ai_router import resolve_provider
    with pytest.raises(ValueError, match="Unknown model"):
        resolve_provider("gpt-4o")


@pytest.mark.asyncio
async def test_generate_routes_to_anthropic():
    from app.services.ai_router import generate_content

    with patch("app.services.ai_router.anthropic_client") as mock_anthropic:
        mock_anthropic.generate_content = AsyncMock(return_value="Hello from Claude")

        result = await generate_content(
            prompt="Say hello to {{name}}",
            variables={"name": "Animesh"},
            model="claude-sonnet-4-6",
        )

        assert result == "Hello from Claude"
        mock_anthropic.generate_content.assert_called_once()


@pytest.mark.asyncio
async def test_generate_routes_to_google():
    from app.services.ai_router import generate_content

    with patch("app.services.ai_router._generate_with_google", new_callable=AsyncMock) as mock_google:
        mock_google.return_value = "Hello from Gemini"

        result = await generate_content(
            prompt="Say hello to {{name}}",
            variables={"name": "Animesh"},
            model="gemini-2.5-flash",
        )

        assert result == "Hello from Gemini"
        mock_google.assert_called_once()
