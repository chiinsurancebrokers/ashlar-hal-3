"""Keeps AI spend proportional to real interest.

HAL's questions, prices and plan cards are deterministic; AI only adds
nicer wording, free-text understanding and explanations. So when a limit is
reached HAL does not refuse anyone: AI calls are simply skipped and HAL
carries on in its deterministic mode.

Limits (all configurable):
* per conversation: ``ai_calls_per_conversation`` AI calls
* per visitor (IP) per day: ``ai_calls_per_ip_per_day`` AI calls
* whole service per day: ``ai_daily_budget_usd`` estimated spend; when it is
  reached an alert email goes to the lead recipient once that day

Counters live in process memory (one Railway instance). If HAL is ever
scaled to several instances, move them to a shared store.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from contextvars import ContextVar
from datetime import date, datetime, timezone
from typing import Any

from backend.app.core.config import Settings, get_settings

log = logging.getLogger("hal.usage")

_request: ContextVar[dict[str, Any] | None] = ContextVar("hal_ai_request", default=None)
_lock = threading.Lock()
_day: date | None = None
_ip_calls: dict[str, int] = {}
_spend_usd = 0.0
_calls_today = 0
_alerted = False


class AIUnavailable(RuntimeError):
    """Raised instead of calling a model; every caller already falls back."""


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _roll() -> None:
    global _day, _ip_calls, _spend_usd, _calls_today, _alerted
    today = _today()
    if _day != today:
        _day, _ip_calls, _spend_usd, _calls_today, _alerted = today, {}, 0.0, 0, False


def reset() -> None:  # tests
    global _day
    with _lock:
        _day = None
        _roll()


def bind(ip: str | None, conversation_calls: int | None = None):
    """Attach the current visitor (and the conversation's AI-call count, if
    any) to AI calls made in this request. Returns a token for ``unbind``."""
    return _request.set({"ip": ip or "unknown", "conv_calls": conversation_calls})


def conversation_calls() -> int | None:
    ctx = _request.get()
    return None if ctx is None else ctx.get("conv_calls")


def unbind(token) -> None:
    _request.reset(token)


def disable_for_request(reason: str) -> None:
    ctx = _request.get()
    if ctx is not None:
        ctx["disabled"] = reason


def check(settings: Settings | None = None) -> None:
    """Call before every model request. Raises AIUnavailable when a limit is reached."""
    global _calls_today
    settings = settings or get_settings()
    ctx = _request.get() or {}
    if ctx.get("disabled"):
        raise AIUnavailable(ctx["disabled"])
    with _lock:
        _roll()
        if _spend_usd >= settings.ai_daily_budget_usd:
            raise AIUnavailable("daily AI budget reached")
        ip = ctx.get("ip")
        if ip and _ip_calls.get(ip, 0) >= settings.ai_calls_per_ip_per_day:
            raise AIUnavailable("visitor daily AI limit reached")
        conv = ctx.get("conv_calls")
        if conv is not None and conv >= settings.ai_calls_per_conversation:
            raise AIUnavailable("conversation AI limit reached")
        if ip:
            _ip_calls[ip] = _ip_calls.get(ip, 0) + 1
        if conv is not None:
            ctx["conv_calls"] = conv + 1
        _calls_today += 1


def record(input_tokens: int | None, output_tokens: int | None, settings: Settings | None = None) -> None:
    """Add the estimated cost of one model response to today's spend."""
    global _spend_usd, _alerted
    settings = settings or get_settings()
    cost = ((input_tokens or 0) * settings.ai_cost_per_mtok_input
            + (output_tokens or 0) * settings.ai_cost_per_mtok_output) / 1_000_000
    alert = False
    with _lock:
        _roll()
        _spend_usd += cost
        if _spend_usd >= settings.ai_daily_budget_usd and not _alerted:
            _alerted = alert = True
    if alert:
        _schedule_alert(settings)


def record_from_payload(payload: dict[str, Any] | None, settings: Settings | None = None) -> None:
    usage = (payload or {}).get("usage") or {}
    record(usage.get("input_tokens") or usage.get("prompt_tokens"),
           usage.get("output_tokens") or usage.get("completion_tokens"), settings)


def snapshot() -> dict[str, Any]:
    with _lock:
        _roll()
        return {"day": _day.isoformat() if _day else None, "ai_calls": _calls_today,
                "estimated_spend_usd": round(_spend_usd, 4), "visitors": len(_ip_calls),
                "budget_reached": _alerted}


def _schedule_alert(settings: Settings) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_send_alert(settings))


async def _send_alert(settings: Settings) -> None:
    try:
        from email.message import EmailMessage
        from backend.app.services.leads import _mail_sender, _send_transactional
        if not settings.gmail_lead_recipient:
            return
        info = snapshot()
        msg = EmailMessage()
        msg["From"] = _mail_sender(settings)
        msg["To"] = settings.gmail_lead_recipient
        msg["Subject"] = "HAL: daily AI budget reached — running without AI until midnight UTC"
        msg.set_content(
            f"HAL reached its daily AI budget (USD {settings.ai_daily_budget_usd:.2f}).\n\n"
            f"AI calls today: {info['ai_calls']}\nVisitors using AI today: {info['visitors']}\n"
            f"Estimated spend: USD {info['estimated_spend_usd']:.2f}\n\n"
            "HAL keeps working (questions, prices, plan cards, proposals) without AI wording until the day resets. "
            "If this was real traffic, raise AI_DAILY_BUDGET_USD in Railway."
        )
        await _send_transactional(msg)
    except Exception as exc:
        log.warning("budget alert failed: %s", exc)
