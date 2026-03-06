from pydantic_settings import BaseSettings


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

    # GoHighLevel
    GHL_API_KEY: str = ""

    # GCP
    GOOGLE_CLOUD_PROJECT: str = ""

    # TTS provider toggle: "gemini" or "chirp"
    TTS_PROVIDER: str = "gemini"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
