from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, field_validator

from backend.app.services.leads import send_saved_quote_email
from backend.app.services.saved_quotes import SavedQuoteError, retrieve_quote, save_quote

router = APIRouter(prefix="/saved-quotes", tags=["saved-quotes"])


class SaveQuoteRequest(BaseModel):
    state: dict[str, Any]
    email: EmailStr
    date_of_birth: str = Field(max_length=10)
    consent: bool

    @field_validator("state")
    @classmethod
    def _limit_state(cls, value: dict[str, Any]) -> dict[str, Any]:
        import json
        if len(json.dumps(value, default=str)) > 20000:
            raise ValueError("State is too large.")
        return value


class RetrieveQuoteRequest(BaseModel):
    reference: str = Field(max_length=40)
    date_of_birth: str = Field(max_length=10)


def _public_base(request: Request) -> str:
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    proto = request.headers.get("x-forwarded-proto") or ("http" if host.startswith(("localhost", "127.0.0.1")) else "https")
    return f"{proto}://{host}"


@router.post("")
async def save(req: SaveQuoteRequest, request: Request):
    try:
        saved = save_quote(state=req.state, email=str(req.email), date_of_birth=req.date_of_birth, consent=req.consent)
    except SavedQuoteError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    retrieve_url = f"{_public_base(request)}/quote/{saved['reference']}"
    try:
        await send_saved_quote_email(saved, str(req.email), retrieve_url)
        email_sent = True
    except Exception:
        email_sent = False  # the quote is saved; the client still sees the reference on screen
    return {"reference": saved["reference"], "valid_until": saved["valid_until"],
            "retrieve_url": retrieve_url, "email_sent": email_sent}


@router.post("/retrieve")
async def retrieve(req: RetrieveQuoteRequest):
    try:
        return retrieve_quote(reference=req.reference, date_of_birth=req.date_of_birth)
    except SavedQuoteError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
