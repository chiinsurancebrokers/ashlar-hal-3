from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import BaseModel, Field

from backend.app.core.config import Settings


class MatchingAgentDecision(BaseModel):
    top_plan_key: str | None = None
    ranked_plan_keys: list[str] = Field(default_factory=list)
    explanation: str
    model_used: bool = False
    model_status: str = "deterministic"


def deterministic_matching_summary(quotes: list[dict[str, Any]], excluded: list[dict[str, Any]], *, greek: bool) -> MatchingAgentDecision:
    """Explain the already-ranked deterministic shortlist without changing it."""
    keys = [str(q.get("plan_key")) for q in quotes if q.get("plan_key")]
    if not quotes:
        return MatchingAgentDecision(top_plan_key=None, ranked_plan_keys=[], explanation="")
    top = quotes[0]
    matched = [str(x) for x in (top.get("matched_requirements") or [])]
    currency = str(top.get("currency") or "EUR")
    try:
        price = f"{currency} {float(top.get('premium')):,.2f}"
    except (TypeError, ValueError):
        price = currency
    if greek:
        why = (f"καλύπτει επαληθευμένα: {', '.join(matched)}" if matched else "είναι η πρώτη επιλογή της deterministic κατάταξης")
        explanation = f"Η κορυφαία επιλογή είναι {top.get('product_name')} ({top.get('insurer')}) στα {price}/έτος — {why}."
        if excluded:
            explanation += f" {len(excluded)} πρόγραμμα{'τα' if len(excluded) != 1 else ''} αποκλείστηκαν από τους deterministic κανόνες."
    else:
        why = (f"it verifiably covers: {', '.join(matched)}" if matched else "it is first in the deterministic ranking")
        explanation = f"HAL's top pick is {top.get('product_name')} ({top.get('insurer')}) at {price}/year — {why}."
        if excluded:
            explanation += f" {len(excluded)} plan{'s' if len(excluded) != 1 else ''} were excluded by deterministic rules."
    return MatchingAgentDecision(top_plan_key=keys[0] if keys else None, ranked_plan_keys=keys, explanation=explanation)


def _extract_output_text(payload: dict[str, Any]) -> str:
    for item in payload.get("output") or []:
        if item.get("type") == "message":
            for part in item.get("content") or []:
                if part.get("type") == "output_text" and part.get("text"):
                    return str(part["text"])
    raise RuntimeError("OpenAI matching agent returned no output_text.")


async def explain_matching(quotes: list[dict[str, Any]], excluded: list[dict[str, Any]], *, greek: bool, settings: Settings) -> MatchingAgentDecision:
    decision = deterministic_matching_summary(quotes, excluded, greek=greek)
    if not quotes or not settings.openai_matching_agent_enabled or not settings.openai_api_key:
        return decision
    packet = {
        "language": "el" if greek else "en",
        "ranked_shortlist": [{
            "plan_key": q.get("plan_key"), "rank": q.get("recommendation_rank"), "insurer": q.get("insurer"),
            "product_name": q.get("product_name"), "premium": q.get("premium"), "currency": q.get("currency"),
            "matched_requirements": q.get("matched_requirements"), "evidence_confidence": q.get("evidence_confidence"),
        } for q in quotes],
        "excluded": [{"plan_key": e.get("plan_key"), "gaps": e.get("gaps")} for e in excluded],
    }
    schema = {"type":"object","properties":{"explanation":{"type":"string"}},"required":["explanation"],"additionalProperties":False}
    request = {
        "model": settings.openai_chat_model,
        "instructions": (
            "You are HAL's Quote & Matching explainer. The supplied order, premiums, eligibility, exclusions, area, deductible and evidence are authoritative. "
            "Explain why the first plan ranks first using only supplied facts. Never rerank, add/remove plans, calculate or alter premiums, infer benefits, or override exclusions. "
            "Keep the answer concise and client-friendly in the requested language."
        ),
        "input": json.dumps(packet, ensure_ascii=False, default=str), "max_output_tokens": settings.openai_matching_agent_max_output_tokens,
        "text":{"format":{"type":"json_schema","name":"hal_matching_explanation","strict":True,"schema":schema}}, "store":False,
    }
    try:
        from backend.app.services import usage_guard
        usage_guard.check(settings)
        async with httpx.AsyncClient(timeout=settings.openai_chat_timeout_seconds) as client:
            response = await client.post("https://api.openai.com/v1/responses", headers={"Authorization":f"Bearer {settings.openai_api_key}","Content-Type":"application/json"}, json=request)
        if not (200 <= response.status_code < 300):
            raise RuntimeError(f"OpenAI matching agent returned {response.status_code}")
        parsed = json.loads(_extract_output_text(response.json()))
        text = str(parsed.get("explanation") or "").strip()
        if text:
            decision.explanation = text
            decision.model_used = True
            decision.model_status = "ok"
    except Exception:
        decision.model_status = "unavailable"
    return decision
