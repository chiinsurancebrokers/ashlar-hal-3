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

    # OpenAI Verifier Agent: second-pass consistency gate after deterministic matching.
    # It may PASS/WARN/BLOCK but never rewrite premiums, eligibility, or evidence.
    openai_verifier_enabled: bool = True
    openai_verifier_max_output_tokens: int = 900
    openai_verifier_timeout_seconds: int = 25

    # Quote & Matching Agent: explains deterministic shortlist facts only.
    openai_matching_agent_enabled: bool = True
    openai_matching_agent_max_output_tokens: int = 900
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

    # Durable HAL conversation/fact-find persistence. The secret service-role
    # key is server-only and must never be exposed to frontend JavaScript.
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None

    # Secure server-to-server bridge to Ashlar Proposal Studio. These values
    # stay on the HAL backend and are never exposed to browser JavaScript.
    proposal_studio_api_url: str | None = None
    proposal_studio_api_key: str | None = None
    proposal_studio_timeout_seconds: int = 90
    current_policy_signing_secret: str | None = None
    # Secret used to hash the date of birth that protects a saved quote.
    # Falls back to the Supabase service-role key when not set.
    quote_retrieval_secret: str | None = None
    # Follow-up / reminder emails for saved quotes (opt-in by the client).
    # Hosts allowed in links that HAL emails to clients (prevents a forged
    # Host header from putting someone else's domain into an Ashlar email).
    public_host_allowlist: str = ("hal.ashlarassurance.com,ashlar-hal-3-production.up.railway.app,"
                                  "ashlar-hal-3-adviser-os-staging.up.railway.app,localhost,127.0.0.1,testserver")
    followups_enabled: bool = False
    followup_poll_seconds: int = 300
    followup_fast_mode: bool = False  # staging only: send within minutes instead of days
    followup_admin_token: str | None = None
    followup_bcc_broker: bool = True
    followup_checkin_days: int = 3
    followup_expiry_days_before: int = 5
    followup_annual_review_days: int = 300

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

    # Resend HTTPS transactional email (preferred on Railway plans where SMTP egress is blocked).
    resend_api_key: str | None = None
    resend_from_email: str = "quotes@ashlarassurance.com"
    resend_from_name: str = "Ashlar Assurance"
    resend_reply_to: str = "info@ashlarassurance.com"

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
