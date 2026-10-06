import logging
import sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from backend.app.core.config import get_settings
from backend.app.core.rate_limit import SimpleRateLimitMiddleware
from backend.app.api.chat import router as chat_router
from backend.app.api.quotes import router as quotes_router
from backend.app.api.leads import router as leads_router
from backend.app.api.travel import router as travel_router
from backend.app.api.voice import router as voice_router
from backend.app.api.healthcare import router as healthcare_router
from backend.app.api.corporate import router as corporate_router
from backend.app.api.sessions import router as sessions_router
from backend.app.api.documents import router as documents_router
from backend.app.api.saved_quotes import router as saved_quotes_router
from backend.app.api.followups import router as followups_router
from backend.app.services.architecture_auditor_agent import audit_architecture

settings = get_settings()

# Make "hal.*" errors (lead delivery, voice, follow-ups) visible in Railway logs
# with their reason, not just the HTTP status code.
_hal_log = logging.getLogger("hal")
if not _hal_log.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    _hal_log.addHandler(_handler)
    _hal_log.setLevel(logging.INFO)
BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(title=settings.app_name, version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

app.add_middleware(
    SimpleRateLimitMiddleware,
    limited_prefixes=(f"{settings.api_prefix}/chat", f"{settings.api_prefix}/leads",
                       f"{settings.api_prefix}/corporate", f"{settings.api_prefix}/sessions",
                       f"{settings.api_prefix}/transcribe", f"{settings.api_prefix}/speak",
                       f"{settings.api_prefix}/saved-quotes", f"{settings.api_prefix}/followups"),
    max_requests=20,
    window_seconds=60,
)

app.include_router(chat_router, prefix=settings.api_prefix)
app.include_router(quotes_router, prefix=settings.api_prefix)
app.include_router(leads_router, prefix=settings.api_prefix)
app.include_router(travel_router, prefix=settings.api_prefix)
app.include_router(voice_router, prefix=settings.api_prefix)
app.include_router(healthcare_router, prefix=settings.api_prefix)
app.include_router(corporate_router, prefix=settings.api_prefix)
app.include_router(sessions_router, prefix=settings.api_prefix)
app.include_router(documents_router, prefix=settings.api_prefix)
app.include_router(saved_quotes_router, prefix=settings.api_prefix)
app.include_router(followups_router, prefix=settings.api_prefix)


@app.on_event("startup")
async def _start_followups() -> None:
    # Reminder emails for saved quotes; off unless FOLLOWUPS_ENABLED=true.
    if settings.followups_enabled and settings.supabase_url and settings.supabase_service_role_key:
        import asyncio
        from backend.app.services.followups import followup_loop
        app.state.followup_task = asyncio.create_task(followup_loop(settings))

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    def homepage():
        html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
        extension = '<script src="/static/corporate-group.js"></script>'
        if extension not in html:
            html = html.replace("</body>", f"{extension}\n</body>")
        return HTMLResponse(
            html,
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
        )


if FRONTEND_DIR.exists():
    @app.get("/quote", include_in_schema=False)
    @app.get("/quote/{reference}", include_in_schema=False)
    def retrieve_page(reference: str | None = None):
        return HTMLResponse(
            (FRONTEND_DIR / "retrieve.html").read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex", "Referrer-Policy": "no-referrer"},
        )


ICONS_DIR = FRONTEND_DIR / "icons"
_ICON_CACHE = {"Cache-Control": "public, max-age=604800"}

if ICONS_DIR.exists():
    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return FileResponse(ICONS_DIR / "favicon.ico", media_type="image/x-icon", headers=_ICON_CACHE)

    @app.get("/favicon.svg", include_in_schema=False)
    def favicon_svg():
        return FileResponse(ICONS_DIR / "favicon.svg", media_type="image/svg+xml", headers=_ICON_CACHE)

    # iOS asks for these names (and the -120x120 variants) when a page is bookmarked.
    @app.get("/apple-touch-icon.png", include_in_schema=False)
    @app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
    @app.get("/apple-touch-icon-120x120.png", include_in_schema=False)
    @app.get("/apple-touch-icon-120x120-precomposed.png", include_in_schema=False)
    def apple_touch_icon():
        return FileResponse(ICONS_DIR / "apple-touch-icon.png", media_type="image/png", headers=_ICON_CACHE)


ROBOTS_TXT = """User-agent: *
Allow: /
Disallow: /quote
Disallow: /api/
"""


@app.get("/robots.txt", include_in_schema=False)
def robots():
    return PlainTextResponse(ROBOTS_TXT, headers={"Cache-Control": "public, max-age=86400"})


@app.get("/health")
def health():
    architecture = audit_architecture(settings)
    return {
        "status": "ok" if architecture.verdict != "BLOCK" else "degraded",
        "service": settings.app_name,
        "environment": settings.app_env,
        "conversational_ai": "claude_messages_api" if settings.anthropic_api_key else "not_configured",
        "voice_transcription": {
            "primary": "elevenlabs_scribe" if settings.elevenlabs_api_key else "not_configured",
            "fallback": "openai_whisper" if settings.openai_api_key else "not_configured",
        },
        "deductible_model": "enabled" if settings.deductible_model_enabled else "disabled_default_pricing",
        "family_pricing": "active",
        "quote_validity_days": settings.quote_validity_days,
        "followups": "enabled" if settings.followups_enabled else "disabled",
        "gmail_lead_delivery": "configured" if all([
            settings.gmail_client_id, settings.gmail_client_secret, settings.gmail_refresh_token,
            settings.gmail_sender_email, settings.gmail_lead_recipient,
        ]) else "not_configured",
        "architecture_audit": architecture.model_dump(mode="json"),
    }
