from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend.app.core.config import get_settings
from backend.app.core.rate_limit import SimpleRateLimitMiddleware
from backend.app.api.adviser import router as adviser_router
from backend.app.api.chat import router as chat_router
from backend.app.api.quotes import router as quotes_router
from backend.app.api.leads import router as leads_router
from backend.app.api.travel import router as travel_router
from backend.app.api.voice import router as voice_router
from backend.app.api.proposals import router as proposals_router

settings = get_settings()
BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(title=settings.app_name, version="1.0.0")

# CORS is explicit rather than left unconfigured. Tighten allow_origins to
# your real production domain(s) once you know them; "*" here only allows
# GET/POST from any origin, no credentials, which is the safest broad
# default for a public quote/chat widget.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.add_middleware(
    SimpleRateLimitMiddleware,
    limited_prefixes=(f"{settings.api_prefix}/adviser", f"{settings.api_prefix}/chat",
                       f"{settings.api_prefix}/leads", f"{settings.api_prefix}/transcribe",
                       f"{settings.api_prefix}/speak", f"{settings.api_prefix}/proposals"),
    max_requests=20,
    window_seconds=60,
)

app.include_router(adviser_router, prefix=settings.api_prefix)
app.include_router(chat_router, prefix=settings.api_prefix)
app.include_router(quotes_router, prefix=settings.api_prefix)
app.include_router(leads_router, prefix=settings.api_prefix)
app.include_router(travel_router, prefix=settings.api_prefix)
app.include_router(voice_router, prefix=settings.api_prefix)
app.include_router(proposals_router, prefix=settings.api_prefix)

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    def homepage():
        # Keep the established HAL page intact and inject the Adviser OS bridge
        # after its existing inline script has created the public UI functions.
        html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
        adviser_bridge = FRONTEND_DIR / "adviser-os.js"
        if adviser_bridge.exists():
            html = html.replace("</body>", '<script src="/static/adviser-os.js"></script>\n</body>')
        return HTMLResponse(
            html,
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
        )


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
        "ashlar_orchestrator": "active",
        "conversational_ai": "claude_messages_api" if settings.anthropic_api_key else "not_configured",
        "voice_transcription": {
            "primary": "elevenlabs_scribe" if settings.elevenlabs_api_key else "not_configured",
            "fallback": "openai_whisper" if settings.openai_api_key else "not_configured",
        },
        "proposal_studio": "embedded",
        "deductible_model": "enabled" if settings.deductible_model_enabled else "disabled_default_pricing",
        "family_pricing": "active",
        "quote_validity_days": settings.quote_validity_days,
        "gmail_lead_delivery": "configured" if all([
            settings.gmail_client_id, settings.gmail_client_secret, settings.gmail_refresh_token,
            settings.gmail_sender_email, settings.gmail_lead_recipient,
        ]) else "not_configured",
    }
