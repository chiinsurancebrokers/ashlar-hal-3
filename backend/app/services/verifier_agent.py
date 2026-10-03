from __future__ import annotations

import json
import re
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from backend.app.core.config import Settings


class VerificationIssue(BaseModel):
    severity: Literal["warn", "block"]
    issue_type: str
    field: str | None = None
    expected: str | None = None
    actual: str | None = None
    evidence: str
    suggested_action: str


class VerificationDecision(BaseModel):
    verdict: Literal["PASS", "WARN", "BLOCK"]
    issues: list[VerificationIssue] = Field(default_factory=list)
    safe_action: Literal["allow", "allow_with_warning", "block_and_review", "rerun_deterministic"]
    model_used: bool = False
    model_status: str = "not_run"


_REQUIREMENT_LABELS = {
    "outpatient_required": "Out-patient cover",
    "maternity_required": "Routine maternity",
    "dental_required": "Routine dental",
    "mental_health_required": "Mental health",
    "wellness_required": "Wellness screening",
    "optical_required": "Optical benefits",
    "evacuation_required": "Medical evacuation",
    "chronic_required": "Chronic condition cover",
}


def _safe_state(state: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "age", "residence_country", "nationality", "coverage_area", "currency",
        "deductible", "deductible_preference", "budget_annual", "client_segment",
        "outpatient_required", "maternity_required", "dental_required",
        "mental_health_required", "wellness_required", "optical_required",
        "evacuation_required", "chronic_required", "chronic_conditions_disclosed",
        "private_hospital_choice_required", "cross_border_treatment_required",
        "home_country_treatment_required", "continuity_portability_required",
        "high_annual_limit_required", "private_room_required", "direct_billing_required",
        "second_medical_opinion_required", "language",
    }
    return {k: state.get(k) for k in allowed if k in state}


def _quote_for_verifier(q: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "plan_key", "insurer", "product_code", "product_name", "eligible",
        "premium", "currency", "coverage_area_label", "official_rate",
        "evidence_status", "evidence_confidence", "requirements_score",
        "matched_requirements", "unmatched_requirements", "verified_facts",
        "reasons", "warnings", "benefit_checklist", "recommended",
        "recommendation_rank", "card_annual_limit", "card_deductible",
    }
    return {k: q.get(k) for k in keys if k in q}


def _area_issue(state: dict[str, Any], quote: dict[str, Any]) -> VerificationIssue | None:
    expected = state.get("coverage_area")
    label = str(quote.get("coverage_area_label") or "").lower()
    if not expected or not label:
        return None
    mismatch = False
    if expected == "area1" and "worldwide" in label:
        mismatch = True
    elif expected in {"area2", "area3", "area4"} and label.startswith("europe"):
        mismatch = True
    if not mismatch:
        return None
    return VerificationIssue(
        severity="block", issue_type="pricing_geography_mismatch", field="coverage_area",
        expected=str(expected), actual=str(quote.get("coverage_area_label") or ""),
        evidence=f"Quote {quote.get('plan_key') or quote.get('product_name')} uses a geographic label inconsistent with the applicant's deterministic area.",
        suggested_action="Rerun deterministic quoting from the applicant's locked coverage_area and do not display this quote.",
    )


def _must_have_issues(state: dict[str, Any], quote: dict[str, Any]) -> list[VerificationIssue]:
    out: list[VerificationIssue] = []
    checklist = {str(item.get("field")): item.get("covered") for item in (quote.get("benefit_checklist") or []) if isinstance(item, dict)}
    matched = set(quote.get("matched_requirements") or [])
    unmatched = set(quote.get("unmatched_requirements") or [])
    confidence = float(quote.get("evidence_confidence") or 0.0)
    for field, label in _REQUIREMENT_LABELS.items():
        if not state.get(field):
            continue
        covered = checklist.get(field)
        if covered is False or label in unmatched:
            out.append(VerificationIssue(
                severity="block", issue_type="must_have_not_covered", field=field,
                expected="covered", actual="not covered",
                evidence=f"{label} is a stated must-have but the verified plan evidence marks it as not covered.",
                suggested_action="Remove the plan from the shortlist and rerun deterministic matching.",
            ))
        elif confidence >= 1.0 and covered is True and label not in matched:
            out.append(VerificationIssue(
                severity="warn", issue_type="matching_metadata_inconsistent", field=field,
                expected=f"{label} in matched_requirements", actual="missing from matched_requirements",
                evidence="Benefit checklist confirms cover but shortlist metadata does not record the matched requirement.",
                suggested_action="Rebuild the shortlist metadata from the deterministic matching engine.",
            ))
    return out


def deterministic_verify(state: dict[str, Any], quotes: list[dict[str, Any]], *, rendered_reply: str = "", expected_greek: bool = False, current_policy: dict[str, Any] | None = None) -> VerificationDecision:
    issues: list[VerificationIssue] = []
    for quote in quotes:
        area = _area_issue(state, quote)
        if area:
            issues.append(area)
        issues.extend(_must_have_issues(state, quote))
        if quote.get("eligible") is False:
            issues.append(VerificationIssue(severity="block", issue_type="ineligible_plan_displayed", field="eligible", expected="true", actual="false", evidence="A plan marked ineligible is present in the client shortlist.", suggested_action="Remove the plan and rerun eligibility."))
        try:
            premium = float(quote.get("premium"))
            if premium <= 0:
                raise ValueError
        except (TypeError, ValueError):
            issues.append(VerificationIssue(severity="block", issue_type="invalid_premium", field="premium", expected="positive numeric annual premium", actual=str(quote.get("premium")), evidence="A displayed shortlist premium is missing, non-numeric, or non-positive.", suggested_action="Recalculate pricing from the deterministic rate engine."))
    if expected_greek and rendered_reply:
        greek_chars = len(re.findall(r"[\u0370-\u03ff]", rendered_reply))
        latin_words = len(re.findall(r"[A-Za-z]{2,}", rendered_reply))
        if greek_chars == 0 and latin_words >= 5:
            issues.append(VerificationIssue(severity="warn", issue_type="language_drift", field="reply", expected="Greek client-facing explanation", actual="predominantly English", evidence="The conversation language is Greek but the rendered shortlist explanation contains no Greek characters.", suggested_action="Regenerate only the explanatory copy in Greek; do not change quote facts."))
    if current_policy:
        rows = current_policy.get("benefit_rows") or []
        seen: dict[str, set[str]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = str(row.get("benefit_code") or "").strip()
            status = str(row.get("status") or "").strip()
            if code and status:
                seen.setdefault(code, set()).add(status)
        for code, statuses in seen.items():
            if "confirmed" in statuses and "not_covered" in statuses:
                issues.append(VerificationIssue(severity="block", issue_type="current_policy_evidence_contradiction", field=code, expected="one consistent evidence status", actual=", ".join(sorted(statuses)), evidence="Current-policy analysis contains opposing statuses for the same benefit code.", suggested_action="Reconcile the current-policy evidence before showing a row-by-row comparison."))
    if any(i.severity == "block" for i in issues):
        return VerificationDecision(verdict="BLOCK", issues=issues, safe_action="block_and_review", model_used=False, model_status="deterministic_block")
    if issues:
        return VerificationDecision(verdict="WARN", issues=issues, safe_action="allow_with_warning", model_used=False, model_status="deterministic_warning")
    return VerificationDecision(verdict="PASS", issues=[], safe_action="allow", model_used=False, model_status="deterministic_pass")


_VERIFIER_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["PASS", "WARN", "BLOCK"]},
        "issues": {"type": "array", "items": {"type": "object", "properties": {
            "severity": {"type": "string", "enum": ["warn", "block"]}, "issue_type": {"type": "string"},
            "field": {"type": ["string", "null"]}, "expected": {"type": ["string", "null"]}, "actual": {"type": ["string", "null"]},
            "evidence": {"type": "string"}, "suggested_action": {"type": "string"}},
            "required": ["severity", "issue_type", "field", "expected", "actual", "evidence", "suggested_action"], "additionalProperties": False}},
        "safe_action": {"type": "string", "enum": ["allow", "allow_with_warning", "block_and_review", "rerun_deterministic"]},
        "model_used": {"type": "boolean"}, "model_status": {"type": "string"}},
    "required": ["verdict", "issues", "safe_action", "model_used", "model_status"], "additionalProperties": False,
}


def _extract_output_text(payload: dict[str, Any]) -> str:
    for item in payload.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "output_text" and content.get("text"):
                return str(content["text"])
    raise RuntimeError("OpenAI verifier returned no output_text.")


def _model_issue_has_blocking_evidence(issue: VerificationIssue, rendered_reply: str) -> bool:
    """Fail closed on facts, not on model uncertainty.

    Deterministic checks already own geography, eligibility, premiums, explicit
    uncovered must-haves and current-policy contradictions. The model may add a
    new BLOCK only when it identifies an unsupported claim actually present in
    the client-facing rendered reply. Unknown benefit evidence, an unset budget,
    or a requested benefit by itself is never a contradiction.
    """
    if issue.severity != "block":
        return True
    if issue.issue_type not in {"unsupported_client_facing_claim", "unsupported_claim"}:
        return False
    evidence = (issue.evidence or "").strip().lower()
    reply = (rendered_reply or "").strip().lower()
    return bool(reply and evidence and any(fragment in reply for fragment in re.findall(r"[a-z0-9€$£][^.!?]{8,80}", evidence)[:3]))


def _normalise_model_decision(decision: VerificationDecision, rendered_reply: str) -> VerificationDecision:
    issues: list[VerificationIssue] = []
    for issue in decision.issues:
        if issue.severity == "block" and not _model_issue_has_blocking_evidence(issue, rendered_reply):
            issue = issue.model_copy(update={
                "severity": "warn",
                "suggested_action": "Review evidence quality without withholding a deterministically valid shortlist.",
            })
        issues.append(issue)
    if any(i.severity == "block" for i in issues):
        verdict, action = "BLOCK", "block_and_review"
    elif issues or decision.verdict == "WARN" or decision.verdict == "BLOCK":
        verdict, action = "WARN", "allow_with_warning"
    else:
        verdict, action = "PASS", "allow"
    return decision.model_copy(update={"verdict": verdict, "safe_action": action, "issues": issues})


async def _openai_verify(*, state: dict[str, Any], quotes: list[dict[str, Any]], excluded: list[dict[str, Any]], rendered_reply: str, expected_greek: bool, settings: Settings, current_policy: dict[str, Any] | None = None) -> VerificationDecision:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    packet = {"applicant_requirements": _safe_state(state), "shortlist": [_quote_for_verifier(q) for q in quotes], "excluded_plans": excluded, "rendered_reply": rendered_reply, "expected_language": "el" if expected_greek else "en", "current_policy": current_policy}
    instructions = (
        "You are HAL's independent insurance output verifier. Audit only the supplied packet. "
        "Do not invent policy terms, premiums, eligibility rules, or evidence. The deterministic engine is authoritative for numeric pricing and explicit rule outputs. "
        "An unset or no-fixed budget is NOT a contradiction. A requested benefit with unknown/unloaded evidence is NOT proof that it is uncovered and must not cause BLOCK. "
        "Do not treat acknowledgement such as 'this is important to you' or 'I will include that as a requirement' as a promise that a plan covers the benefit. "
        "Return BLOCK only for a concrete contradiction or an unsupported factual claim that is actually present in rendered_reply. "
        "Return WARN for presentation/language/evidence-quality concerns. Never propose a new premium or rewrite factual values."
    )
    request = {"model": settings.openai_chat_model, "instructions": instructions, "input": json.dumps(packet, ensure_ascii=False, default=str), "max_output_tokens": settings.openai_verifier_max_output_tokens, "text": {"format": {"type": "json_schema", "name": "hal_verifier_decision", "strict": True, "schema": _VERIFIER_SCHEMA}}, "store": False}
    async with httpx.AsyncClient(timeout=settings.openai_verifier_timeout_seconds) as client:
        response = await client.post("https://api.openai.com/v1/responses", headers={"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"}, json=request)
    if not (200 <= response.status_code < 300):
        raise RuntimeError(f"OpenAI verifier returned {response.status_code}: {(response.text or '')[:240]}")
    parsed = json.loads(_extract_output_text(response.json()))
    decision = VerificationDecision.model_validate(parsed)
    decision.model_used = True
    decision.model_status = "ok"
    return _normalise_model_decision(decision, rendered_reply)


async def verify_shortlist(state: dict[str, Any], quotes: list[dict[str, Any]], excluded: list[dict[str, Any]], *, rendered_reply: str, expected_greek: bool, settings: Settings, current_policy: dict[str, Any] | None = None) -> VerificationDecision:
    deterministic = deterministic_verify(state, quotes, rendered_reply=rendered_reply, expected_greek=expected_greek, current_policy=current_policy)
    if deterministic.verdict == "BLOCK":
        return deterministic
    if not settings.openai_verifier_enabled or not settings.openai_api_key:
        return deterministic
    try:
        model_decision = await _openai_verify(state=state, quotes=quotes, excluded=excluded, rendered_reply=rendered_reply, expected_greek=expected_greek, settings=settings, current_policy=current_policy)
    except Exception as exc:
        issues = list(deterministic.issues)
        issues.append(VerificationIssue(severity="warn", issue_type="verifier_unavailable", field=None, expected="OpenAI verifier available", actual=type(exc).__name__, evidence="The deterministic checks passed, but the second-pass model verifier was unavailable.", suggested_action="Allow deterministic output, log the verifier outage, and retry verification on a later request."))
        return VerificationDecision(verdict="WARN", issues=issues, safe_action="allow_with_warning", model_used=False, model_status="unavailable")
    combined = list(deterministic.issues) + model_decision.issues
    if any(i.severity == "block" for i in combined):
        verdict, action = "BLOCK", "block_and_review"
    elif combined or model_decision.verdict == "WARN":
        verdict, action = "WARN", "allow_with_warning"
    else:
        verdict, action = "PASS", "allow"
    return VerificationDecision(verdict=verdict, issues=combined, safe_action=action, model_used=True, model_status="ok")
