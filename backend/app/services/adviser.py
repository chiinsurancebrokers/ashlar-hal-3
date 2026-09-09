from __future__ import annotations
import json
import re
from typing import Any

from backend.app.services.openai_client import adviser_response
from backend.app.schemas.quote import QuoteResult
from backend.app.knowledge.service import fairness_rules, international_vs_local, fairness_check

BOOL_FIELDS = {
    "outpatient_required", "maternity_required", "dental_required", "mental_health_required",
    "wellness_required", "optical_required", "evacuation_required", "chronic_required",
    "chronic_conditions_disclosed", "private_hospital_choice_required", "cross_border_treatment_required",
    "home_country_treatment_required", "continuity_portability_required", "high_annual_limit_required",
    "private_room_required", "direct_billing_required", "second_medical_opinion_required",
}
STRING_FIELDS = {"first_name", "residence_country", "nationality", "client_segment", "journey", "chronic_conditions_note"}
ALLOWED_FIELDS = {"age", "coverage_area", "currency", "deductible", "budget_annual", *BOOL_FIELDS, *STRING_FIELDS}


def _extract_json(text: str) -> dict:
    raw = (text or "").strip()
    if not raw:
        return {}
    cleaned = raw
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I | re.S).strip()
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass
    m = re.search(r"\{.*\}", cleaned, flags=re.S)
    if m:
        try:
            parsed = json.loads(m.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            pass
    return {}


def clean_applicant_updates(updates: dict[str, Any]) -> dict[str, Any]:
    """Whitelist + type-coerce whatever the LLM extracted. This is the hard
    boundary: nothing outside ALLOWED_FIELDS, and nothing outside its
    expected type, ever reaches the deterministic engine's applicant state."""
    clean: dict[str, Any] = {}
    for key, value in (updates or {}).items():
        if key not in ALLOWED_FIELDS or value is None:
            continue
        if key in BOOL_FIELDS:
            clean[key] = bool(value)
        elif key == "age":
            try:
                v = int(value)
                if 0 <= v <= 120:
                    clean[key] = v
            except Exception:
                pass
        elif key in {"deductible", "budget_annual"}:
            try:
                v = float(value)
                if v >= 0:
                    clean[key] = v
            except Exception:
                pass
        elif key == "coverage_area":
            if value in {"area1", "area2", "area3", "area4"}:
                clean[key] = value
        elif key in STRING_FIELDS:
            clean[key] = str(value)[:200]
    return clean


def _fairness_clause() -> str:
    rules = fairness_rules()
    prohibited = "\n".join(f"  - Never say or imply: {c}" for c in rules["prohibited_claims"])
    required = "\n".join(f"  - Always acknowledge when relevant: {a}" for a in rules["required_acknowledgements"])
    return f"Fairness rules (hard constraints):\n{prohibited}\n{required}"


def build_intake_instructions(state: dict, greek: bool) -> str:
    return f"""You are HAL's applicant-understanding layer for Ashlar Assurance.

Return one JSON object only:
{{"acknowledgement": "one short natural acknowledgement, never a question", "applicant_updates": {{}}}}

Rules:
- Converse in {"Greek" if greek else "English"}.
- acknowledgement must be at most two short sentences.
- Do not ask the next insurance question; HAL's deterministic discovery engine does that.
- Do not calculate premiums, decide eligibility, or state which plans are recommended — that is the deterministic engine's job, not yours.
- Do not invent benefits, exclusions, underwriting outcomes or eligibility.
- Extract only facts the applicant actually stated or clearly confirmed.
- Never infer nationality from residence.
- Use only these applicant_updates keys: {", ".join(sorted(ALLOWED_FIELDS))}.

Current state:
{json.dumps(state, ensure_ascii=False)}
"""


async def intake_analysis(message: str, state: dict, history: list[dict] | None, greek: bool) -> dict:
    try:
        text = await adviser_response(
            instructions=build_intake_instructions(state, greek),
            message=message, history=history, json_mode=True, max_output_tokens=500,
        )
        parsed = _extract_json(text)
        return {
            "acknowledgement": str(parsed.get("acknowledgement", "") or "").strip(),
            "applicant_updates": clean_applicant_updates(parsed.get("applicant_updates", {})),
        }
    except Exception:
        return {"acknowledgement": "", "applicant_updates": {}}


def build_explain_plan_instructions(quote: QuoteResult, greek: bool) -> str:
    """The ONLY facts this prompt is allowed to state about the plan are the
    ones explicitly listed below, all sourced from the evidence layer. It
    cannot see the internet, training data, or "general knowledge" about
    this insurer — only this list."""
    facts = "\n".join(f"- {f}" for f in quote.verified_facts) or "- (no additional verified facts loaded for this plan)"
    return f"""You are HAL, explaining ONE specific insurance plan to an applicant, in {"Greek" if greek else "English"}.

Plan: {quote.insurer} — {quote.product_name}
Annual premium: {quote.currency} {quote.premium:,.2f}
Matched requirements (verified): {", ".join(quote.matched_requirements) or "none selected"}
Unmatched requirements (verified): {", ".join(quote.unmatched_requirements) or "none"}

The ONLY verified facts about this plan you may state:
{facts}

Hard rules:
- Never state a benefit, limit, waiting period or exclusion that is not in the verified facts list above.
- If asked about something not in that list, say it is not confirmed in the loaded policy evidence rather than guessing.
- Do not restate the premium as anything other than the figure given above.
- Keep the explanation warm, concise, advisory — 3-5 sentences.

{_fairness_clause()}
"""


async def explain_plan(quote: QuoteResult, question: str, greek: bool) -> str:
    try:
        text = await adviser_response(instructions=build_explain_plan_instructions(quote, greek), message=question, max_output_tokens=400)
        flags = fairness_check(text)
        if flags:
            # Fail closed to a safe deterministic fallback rather than ever
            # surface a flagged claim to a client.
            return _deterministic_plan_summary(quote, greek)
        return text
    except Exception:
        return _deterministic_plan_summary(quote, greek)


def _deterministic_plan_summary(quote: QuoteResult, greek: bool) -> str:
    facts = "; ".join(quote.verified_facts[:3])
    if greek:
        return f"{quote.product_name} ({quote.insurer}): {quote.currency} {quote.premium:,.2f}/έτος. {facts}"
    return f"{quote.product_name} ({quote.insurer}): {quote.currency} {quote.premium:,.2f}/year. {facts}"


def build_local_review_instructions(greek: bool) -> str:
    playbook = international_vs_local()["local_review_playbook"]
    steps = "\n".join(f"{i+1}. {s}" for i, s in enumerate(playbook["steps"]))
    return f"""You are HAL. The applicant has asked about LOCAL (domestic-only) health insurance.

Guiding principle: {playbook['principle']}

Follow this playbook:
{steps}

{_fairness_clause()}

Converse in {"Greek" if greek else "English"}. Keep it to 3-5 sentences and end with a genuine question about what matters most to them (price, Greece-only cover, private hospital access, family cover, etc.) — do not lecture.
"""
