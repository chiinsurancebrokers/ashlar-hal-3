"""Durable storage for HAL leads (Supabase table public.hal_leads).

Every proposal request and comparison request is written here BEFORE any
email is sent. If the adviser email then fails, the lead is still on record
with delivery_status='failed' and the error, so nobody is lost because a
mail key expired. See sql/hal_leads.sql for the table.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from backend.app.core.config import Settings, get_settings

log = logging.getLogger("hal.leads")

_TABLE = "hal_leads"


def _rest(settings: Settings) -> tuple[str, dict[str, str]]:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError("Lead storage is not configured (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY).")
    key = settings.supabase_service_role_key
    return (f"{settings.supabase_url.rstrip('/')}/rest/v1/{_TABLE}",
            {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"})


async def store_lead(kind: str, reference: str, payload: dict[str, Any], settings: Settings | None = None) -> None:
    """Insert the lead with delivery_status='pending'. Raises on failure."""
    settings = settings or get_settings()
    url, headers = _rest(settings)
    name = " ".join(x for x in [str(payload.get("first_name") or "").strip(),
                                str(payload.get("last_name") or "").strip()] if x) or str(payload.get("name") or "").strip()
    row = {
        "reference": reference,
        "kind": kind,
        "email": str(payload.get("email") or "").strip(),
        "name": name or None,
        "phone": str(payload.get("phone") or "").strip() or None,
        "insurance_interest": str(payload.get("insurance_interest") or "").strip() or None,
        "payload": payload,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(url, headers={**headers, "Prefer": "return=minimal"}, json=row)
    if not (200 <= response.status_code < 300):
        raise RuntimeError(f"Supabase returned {response.status_code}: {(response.text or '')[:300]}")


async def mark_delivery(reference: str, *, sent: bool, transport: str | None = None,
                        error: str | None = None, settings: Settings | None = None) -> None:
    """Record whether the adviser email went out. Never raises (logged instead)."""
    try:
        settings = settings or get_settings()
        url, headers = _rest(settings)
        patch: dict[str, Any] = {"delivery_status": "sent" if sent else "failed",
                                 "transport": transport, "delivery_error": (error or None) and error[:1000]}
        if sent:
            patch["delivered_at"] = datetime.now(timezone.utc).isoformat()
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.patch(url, headers={**headers, "Prefer": "return=minimal"},
                                          params={"reference": f"eq.{reference}"}, json=patch)
        if not (200 <= response.status_code < 300):
            log.error("lead %s: could not record delivery status (Supabase %s): %s",
                      reference, response.status_code, (response.text or "")[:300])
    except Exception as exc:  # pragma: no cover - defensive
        log.error("lead %s: could not record delivery status: %s", reference, exc)
