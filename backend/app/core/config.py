from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "Ashlar Advisor"
    api_prefix: str = "/api/v1"

    # Claude powers HAL's chat/intake/explain layer — the 'first analysis'.
    anthropic_api_key: str | None = None
    anthropic_chat_model: str = "claude-sonnet-5"
    anthropic_chat_max_tokens: int = 1400
    anthropic_chat_timeout_seconds: int = 60

    # OpenAI stays configured for two things only: (1) speech-to-text, since
    # the Anthropic API has no transcription endpoint, and (2) reserved for
    # the future deep policy-wording comparison feature — not the chat layer.
    openai_api_key: str | None = None
    openai_chat_model: str = "gpt-5.6-terra"
    openai_chat_max_output_tokens: int = 1400
    openai_chat_timeout_seconds: int = 60
    max_audio_upload_mb: int = 20

    elevenlabs_api_key: str | None = None
    elevenlabs_voice_id: str | None = None
    elevenlabs_voice_id_el: str | None = None
    # "George" — warm, articulate British male voice from ElevenLabs' standard
    # library. Explicit ELEVENLABS_VOICE_ID_EN in the environment overrides this.
    elevenlabs_voice_id_en: str | None = "JBFqnCBsd6RMkjVDRZzb"
    elevenlabs_transcribe_model: str = "scribe_v2"
    openai_transcribe_model: str = "whisper-1"

    database_url: str | None = None

    # SECURITY: admin_password has NO default. If it is not set, the admin
    # endpoint refuses every request (fail-closed) instead of silently
    # allowing unauthenticated access. See api/admin.py.
    admin_password: str | None = None

    # Gmail API lead delivery (OAuth 2.0)
    gmail_client_id: str | None = None
    gmail_client_secret: str | None = None
    gmail_refresh_token: str | None = None
    gmail_sender_email: str | None = None
    gmail_lead_recipient: str | None = None

    # --- Quote engine business rules ---------------------------------------
    # A deductible-tiered rate table is not yet confirmed by any carrier, so
    # this model is OFF by default. It only activates once you've reviewed
    # the discount percentages in rates/deductible_model.py and flip this on.
    deductible_model_enabled: bool = False

    # Family/administration discount applied when >=2 lives are quoted on the
    # same policy. Illustrative until a carrier confirms its own figure.
    family_discount_pct: float = 0.05

    # How many days a displayed quote is treated as current before HAL should
    # tell the client to re-check pricing.
    quote_validity_days: int = 30

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
