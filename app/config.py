import structlog
from pydantic_settings import BaseSettings

logger = structlog.get_logger(__name__)


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://localhost/wavelength"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 5

    # JWT Authentication
    JWT_SECRET: str = "CHANGE-ME-IN-PRODUCTION"
    JWT_ALGORITHM: str = "HS256"

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

    # Webhook auth (for external triggers like GHL)
    WEBHOOK_API_KEY: str = ""

    # GCP / Vertex AI
    GOOGLE_CLOUD_PROJECT: str = ""
    GOOGLE_APPLICATION_CREDENTIALS: str = ""
    VERTEX_AI_LOCATION: str = "asia-southeast1"

    # Sarvam AI TTS
    SARVAM_API_KEY: str = ""

    # Groq (OpenAI-compatible LLM)
    GROQ_API_KEY: str = ""

    # --- Audio quality feature flags (Phase 0-4) ---
    # Phase 1: Plivo server-side noise cancellation on incoming audio
    PLIVO_NOISE_CANCEL: bool = True
    # Phase 2: Full echo gate — mutes incoming audio during bot speech + echo tail
    ECHO_GATE_ENABLED: bool = True
    # Echo tail delay (ms) after BotStoppedSpeakingFrame before gate opens.
    # Set from Phase 0 measurement (p95 RTT + 100ms margin). 500ms is a safe default.
    ECHO_TAIL_MS: float = 250.0
    # Phase 3: Pre-synthesize greeting and send directly to Plivo (bypass pipeline)
    GREETING_DIRECT_PLAY: bool = True
    # Phase 4: Adaptive phrase aggregation (lower first-phrase, higher subsequent)
    ADAPTIVE_PHRASE_CHARS: bool = True
    # Phase 4: Comfort noise during inter-sentence silence gaps
    COMFORT_NOISE_ENABLED: bool = False

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
