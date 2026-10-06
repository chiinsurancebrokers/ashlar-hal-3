from __future__ import annotations

import json
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from backend.app.core.config import Settings
from backend.app.schemas.applicant import Applicant
from backend.app.rates.registry import load_rates
from backend.app.evidence.eligibility_rules import (
    active_profile_for_plan,
    evaluate_plan_eligibility,
    profile_missing_fields,
)


class EligibilityPlanAudit(BaseModel):
    plan_key: str
    carrier: str
    product_code: str
    status: Literal["eligible", "ineligible", "unknown"]
    profile: str | None = None
    reason: str
    missing_fields: list[str] = Field(default_factory=list)


class EligibilityAgentDecision(BaseModel):
    verdict: Literal["PASS", "NEEDS_INFO", "BLOCK"]
    plans: list[EligibilityPlanAudit] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    explanation: str
    model_used: bool = False
    model_status: str = "not_run"


def _candidate_products(applicant: Applicant) -> list[tuple[str, str]]:
    seen: list[tuple[str, str]] = []
    for row in load_rates():
        if row.area != applicant.coverage_area:
            continue
        key = (row.carrier, row.product_code)
        if key not in seen:
            seen.append(key)
    return seen


def deterministic_eligibility_audit(applicant: Applicant) -> EligibilityAgentDecision:
    audits: list[EligibilityPlanAudit] = []
    for carrier, product_code in _candidate_products(applicant):
        decision = evaluate_plan_eligibility(applicant, carrier, product_code)
        profile = active_profile_for_plan(carrier, product_code)
        missing = profile_missing_fields(applicant, profile) if profile else []
        audits.append(EligibilityPlanAudit(
            plan_key=f"{carrier}:{product_code}",
            carrier=carrier,
            product_code=product_code,
            status=decision.status,
            profile=decision.profile,
            reason=decision.reason,
            missing_fields=missing,
        ))

    if not audits:
        return EligibilityAgentDecision(
            verdict="BLOCK",
            plans=[],
            missing_fields=[],
            explanation="No products are configured for the selected coverage area.",
            model_used=False,
            model_status="deterministic_no_candidates",
        )

    eligible = [p for p in audits if p.status == "eligible"]
    unknown = [p for p in audits if p.status == "unknown"]
    missing = sorted({f for p in unknown for f in p.missing_fields})

    if eligible:
        verdict = "NEEDS_INFO" if unknown else "PASS"
        explanation = (
            "At least one product is deterministically eligible. "
            + ("Some products need additional eligibility information." if unknown else "No active eligibility rule is unresolved.")
        )
    elif unknown:
        verdict = "NEEDS_INFO"
        explanation = "No product can yet be confirmed eligible because required eligibility information is missing."
    else:
        verdict = "BLOCK"
        explanation = "All configured products are deterministically ineligible under the active eligibility rules."

    return EligibilityAgentDecision(
        verdict=verdict,
        plans=audits,
        missing_fields=missing,
        explanation=explanation,
        model_used=False,
        model_status="deterministic",
    )


_AGENT_SCHEMA = {
    "type": "object",
    "properties": {
        "explanation": {"type": "string"},
        "questions": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["explanation", "questions"],
    "additionalProperties": False,
}


def _extract_output_text(payload: dict[str, Any]) -> str:
    for item in payload.get("output") or []:
        if item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if part.get("type") == "output_text" and part.get("text"):
                return str(part["text"])
    raise RuntimeError("OpenAI eligibility agent returned no output_text.")


async def _explain_with_openai(
    deterministic: EligibilityAgentDecision,
    *,
    greek: bool,
    settings: Settings,
) -> tuple[str, str]:
    """Ask OpenAI only to explain deterministic eligibility results.

    The model is never asked for, and cannot override, any plan status.
    """
    packet = {
        "verdict": deterministic.verdict,
        "missing_fields": deterministic.missing_fields,
        "plans": [
            {
                "plan_key": p.plan_key,
                "status": p.status,
                "profile": p.profile,
                "reason": p.reason,
                "missing_fields": p.missing_fields,
            }
            for p in deterministic.plans
        ],
        "language": "el" if greek else "en",
    }
    instructions = (
        "You are HAL's Eligibility Specialist. Explain only the deterministic eligibility audit supplied to you. "
        "You must not change a plan's eligibility status, infer undocumented carrier rules, mention a premium, "
        "or invent missing requirements. If information is missing, ask only for the fields explicitly listed. "
        "Keep the explanation concise and client-friendly."
    )
    request = {
        "model": settings.openai_chat_model,
        "instructions": instructions,
        "input": json.dumps(packet, ensure_ascii=False),
        "max_output_tokens": min(settings.openai_chat_max_output_tokens, 700),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "hal_eligibility_explanation",
                "strict": True,
                "schema": _AGENT_SCHEMA,
            }
        },
        "store": False,
    }
    from backend.app.services import usage_guard
    usage_guard.check(settings)
    async with httpx.AsyncClient(timeout=settings.openai_chat_timeout_seconds) as client:
        response = await client.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json=request,
        )
    if not (200 <= response.status_code < 300):
        raise RuntimeError(f"OpenAI eligibility agent returned {response.status_code}: {(response.text or '')[:200]}")
    data = response.json()
    usage_guard.record_from_payload(data, settings)
    parsed = json.loads(_extract_output_text(data))
    explanation = str(parsed.get("explanation") or deterministic.explanation).strip()
    questions = [str(q).strip() for q in (parsed.get("questions") or []) if str(q).strip()]
    if questions:
        explanation = explanation + " " + " ".join(questions)
    return explanation, "ok"


async def assess_eligibility(
    applicant: Applicant,
    *,
    greek: bool,
    settings: Settings,
) -> EligibilityAgentDecision:
    deterministic = deterministic_eligibility_audit(applicant)

    # The model adds value only when a rule is actually restrictive or unresolved.
    # For a clean PASS with no active issue, avoid an unnecessary model call.
    if deterministic.verdict == "PASS" or not settings.openai_api_key:
        return deterministic

    try:
        explanation, status = await _explain_with_openai(
            deterministic,
            greek=greek,
            settings=settings,
        )
        deterministic.explanation = explanation
        deterministic.model_used = True
        deterministic.model_status = status
    except Exception:
        # Fail-safe: keep the deterministic decision untouched.
        deterministic.model_used = False
        deterministic.model_status = "unavailable"
    return deterministic
