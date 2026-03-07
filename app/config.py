import structlog
from pydantic_settings import BaseSettings

logger = structlog.get_logger(__name__)


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://localhost/wavelength"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 5

    # Public URL (for Plivo webhooks)
    PUBLIC_BASE_URL: str = "http://localhost:8080"
    PUBLIC_HOST: str = "localhost:8080"

    # Deepgram
    DEEPGRAM_API_KEY: str = ""

    # Google AI (Gemini LLM)
    GOOGLE_AI_API_KEY: str = ""
    # Comma-separated pool of keys (takes priority over GOOGLE_AI_API_KEY)
    GOOGLE_AI_API_KEYS: str = ""

    # GoHighLevel
    GHL_API_KEY: str = ""

    # GCP
    GOOGLE_CLOUD_PROJECT: str = ""

    # Sarvam AI TTS
    SARVAM_API_KEY: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()


class GeminiKeyPool:
    """Round-robin pool of Gemini API keys to spread load across quotas."""

    def __init__(self):
        keys: list[str] = []
        if settings.GOOGLE_AI_API_KEYS:
            keys = [k.strip() for k in settings.GOOGLE_AI_API_KEYS.split(",") if k.strip()]
        if not keys and settings.GOOGLE_AI_API_KEY:
            keys = [settings.GOOGLE_AI_API_KEY]
        self._keys = keys
        self._index = 0

    @property
    def size(self) -> int:
        return len(self._keys)

    def get_key(self) -> str:
        """Return the next API key in round-robin order."""
        if not self._keys:
            return settings.GOOGLE_AI_API_KEY
        key = self._keys[self._index % len(self._keys)]
        self._index += 1
        return key


gemini_key_pool = GeminiKeyPool()
logger.info("gemini_key_pool_initialized", pool_size=gemini_key_pool.size)
