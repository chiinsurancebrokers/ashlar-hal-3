"""Grounded client comparison built only from verified/structured plan data.

The matrix and model payload are deterministic. An LLM may later write client-
facing prose from this payload, but it is not allowed to invent plan facts or
silently alter the comparison matrix.
"""
from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from backend.app.cases.models import AshlarCase


BENEFIT_ORDER = [
    ("inpatient", "In-patient treatment"),
    ("outpatient", "Out-patient treatment"),
    ("cancer", "Cancer / oncology"),
    ("chronic_conditions", "Chronic conditions"),
    ("mental_health", "Mental health"),
    ("maternity", "Maternity"),
    ("dental", "Dental"),
    ("optical", "Optical"),
    ("diagnostics_imaging", "Diagnostics / advanced imaging"),
    ("preventive", "Preventive / wellness"),
    ("evacuation_repatriation", "Evacuation / repatriation"),
]


def _safe(value: Any) -> str:
    if value is None:
        return "Not specified"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    text = str(value).strip()
    return text or "Not specified"


def plan_display_name(result: dict) -> str:
    analysis = result.get("analysis") or {}
    provider = analysis.get("provider") or result.get("provider") or "Provider"
    plan = analysis.get("plan_name") or result.get("target_plan") or "Plan"
    return f"{provider} - {plan}"


def premium_display(analysis: dict) -> str:
    premium = analysis.get("premium") or {}
    amount = premium.get("amount")
    if amount in (None, "", "Not specified"):
        return "Not specified"
    return " ".join(
        part for part in (
            str(premium.get("currency") or "").strip(),
            str(amount).strip(),
            str(premium.get("frequency") or "").strip(),
        ) if part
    )


def build_comparison_matrix(results: list[dict], *, case: AshlarCase | None = None) -> list[dict]:
    """Build the factual comparison matrix without LLM interpretation."""
    names = [plan_display_name(result) for result in results]
    rows: list[dict] = []

    def add(topic: str, getter, category: str) -> None:
        rows.append({
            "category": category,
            "topic": topic,
            "values": {
                name: _safe(getter(result.get("analysis") or {}))
                for name, result in zip(names, results)
            },
        })

    add("Premium", premium_display, "Financial")
    add("Annual policy limit", lambda a: a.get("annual_limit"), "Financial")
    add("Deductible / excess", lambda a: a.get("deductible_or_excess"), "Financial")
    add("Area of cover", lambda a: a.get("area_of_cover"), "Core")
    add("Underwriting basis", lambda a: (a.get("underwriting") or {}).get("basis"), "Underwriting")
    add("Pre-existing conditions", lambda a: (a.get("underwriting") or {}).get("pre_existing_conditions"), "Underwriting")

    maternity_relevant = bool(case and case.applicant and case.applicant.maternity_required)
    for key, label in BENEFIT_ORDER:
        if key == "maternity" and not maternity_relevant:
            continue
        add(label, lambda a, k=key: (a.get("benefits") or {}).get(k), "Benefits")
    return rows


def _source_digest(result: dict, limit: int = 14) -> list[dict]:
    analysis = result.get("analysis") or {}
    evidence: list[dict] = []
    seen: set[tuple] = set()
    for item in analysis.get("source_evidence") or []:
        if not isinstance(item, dict):
            continue
        key = (str(item.get("field") or ""), str(item.get("document") or ""), str(item.get("page") or ""))
        if key in seen:
            continue
        seen.add(key)
        evidence.append({
            "field": item.get("field"),
            "value": item.get("value"),
            "document": item.get("document"),
            "page": item.get("page"),
            "evidence": item.get("evidence"),
        })
        if len(evidence) >= limit:
            return evidence

    for row in result.get("focused_rows") or []:
        key = (str(row.get("benefit") or ""), str(row.get("source_file") or ""), str(row.get("page") or ""))
        if key in seen:
            continue
        seen.add(key)
        evidence.append({
            "field": row.get("benefit"),
            "value": row.get("value"),
            "document": row.get("source_file") or "Target-plan table evidence",
            "page": row.get("page"),
            "evidence": "Geometrically isolated target-plan table row",
        })
        if len(evidence) >= limit:
            break
    return evidence


def build_grounded_case_payload(case: AshlarCase, results: list[dict]) -> dict:
    """Build the only factual payload that an advisory-writing model may use."""
    plans = []
    for result in results:
        analysis = result.get("analysis") or {}
        plans.append({
            "display_name": plan_display_name(result),
            "provider": analysis.get("provider") or result.get("provider"),
            "plan_name": analysis.get("plan_name") or result.get("target_plan"),
            "premium": analysis.get("premium"),
            "deductible_or_excess": analysis.get("deductible_or_excess"),
            "annual_limit": analysis.get("annual_limit"),
            "area_of_cover": analysis.get("area_of_cover"),
            "underwriting": analysis.get("underwriting"),
            "benefits": analysis.get("benefits"),
            "waiting_periods": analysis.get("waiting_periods"),
            "optional_benefits": analysis.get("optional_benefits"),
            "critical_limitations": analysis.get("critical_limitations"),
            "confidence": analysis.get("confidence"),
            "source_evidence": _source_digest(result),
        })

    applicant = case.applicant
    applicant_summary = None
    if applicant:
        applicant_summary = {
            "age": applicant.age,
            "residence_country": applicant.residence_country,
            "coverage_area": applicant.coverage_area,
            "budget_annual": applicant.budget_annual,
            "family_size": applicant.family_size() if hasattr(applicant, "family_size") else 1 + len(applicant.dependents),
            "must_have_keys": (
                applicant.must_have_keys() if hasattr(applicant, "must_have_keys") else [
                    key for key in (
                        "outpatient_required", "maternity_required", "dental_required",
                        "mental_health_required", "wellness_required", "optical_required",
                        "evacuation_required", "chronic_required",
                    ) if getattr(applicant, key, False)
                ]
            ),
            # The free-text medical note is deliberately excluded from the generic
            # report-writing payload. A disclosure flag is enough at this stage.
            "medical_disclosure_flag": applicant.chronic_conditions_disclosed,
        }

    return {
        "case_reference": str(case.case_id),
        "client_name": case.client.display_name or "Client",
        "preferred_language": case.client.preferred_language,
        "needs_profile": case.needs_profile,
        "applicant": applicant_summary,
        "plans": plans,
        "comparison_matrix": build_comparison_matrix(results, case=case),
    }


CLIENT_REPORT_PROMPT = """You are the advisory-writing layer inside Ashlar HAL.
Use ONLY the supplied structured case payload. Do not add product knowledge or
insurance facts that are absent from the payload.

Rules:
- Applicant-specific quote facts outrank generic material.
- Never describe an optional benefit as selected unless the payload confirms it.
- Do not invent numeric scores or rank plans using an arbitrary AI score.
- Compare the final quoted configurations, not product packaging architecture.
- Do not force a single recommendation when the evidence supports a genuine
  trade-off; in that case leave recommended_provider and recommended_plan empty.
- If you recommend one plan, explain the trade-offs against the strongest
  alternative using the client's stated needs and the factual matrix.
- Never infer health status from age, occupation or demographic profile.
- Keep MRI/CT/PET under diagnostics/imaging, not wellness.
- Cite document/page evidence in plain text when the payload provides it.
- Be concise, independent and suitable to send directly to a client.
- Return JSON only.
"""


def build_client_report_prompt(payload: dict, *, language: str = "en") -> str:
    return (
        CLIENT_REPORT_PROMPT
        + f"\nLanguage: {'Greek' if language == 'el' else 'English'}\n"
        + "\n=== GROUNDED CASE PAYLOAD ===\n"
        + json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    )


class PlanNarrative(BaseModel):
    provider: str = Field(min_length=1)
    plan_name: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    strengths: list[str] = Field(default_factory=list)
    considerations: list[str] = Field(default_factory=list)


class AshlarAssessment(BaseModel):
    recommended_provider: str = ""
    recommended_plan: str = ""
    headline: str = Field(min_length=1)
    reasoning: list[str] = Field(default_factory=list)

    @field_validator("reasoning")
    @classmethod
    def reasoning_has_content(cls, value: list[str]) -> list[str]:
        if not any(str(item).strip() for item in value):
            raise ValueError("Ashlar assessment reasoning is empty")
        return value


class ClientReport(BaseModel):
    report_title: str = Field(min_length=1)
    executive_summary: str = Field(min_length=1)
    plans: list[PlanNarrative] = Field(min_length=1)
    key_differences: list[dict] = Field(default_factory=list)
    ashlar_assessment: AshlarAssessment
    important_considerations: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(min_length=1)
    disclaimer: str = Field(min_length=1)


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def validate_client_report(report: dict, results: list[dict]) -> dict:
    """Reject partial report structures without forcing a winner."""
    try:
        ClientReport.model_validate(report)
    except ValidationError as exc:
        raise ValueError(f"Client report failed schema validation: {exc}") from exc

    expected = [
        (
            _norm((result.get("analysis") or {}).get("provider") or result.get("provider")),
            _norm((result.get("analysis") or {}).get("plan_name") or result.get("target_plan")),
        )
        for result in results
    ]
    received = [(_norm(plan.get("provider")), _norm(plan.get("plan_name"))) for plan in report.get("plans") or []]
    missing = []
    for expected_provider, expected_plan in expected:
        if not any(
            expected_provider and received_provider and (expected_provider == received_provider or expected_provider in received_provider or received_provider in expected_provider)
            and expected_plan and received_plan and (expected_plan == received_plan or expected_plan in received_plan or received_plan in expected_plan)
            for received_provider, received_plan in received
        ):
            missing.append(f"{expected_provider or 'provider'} / {expected_plan or 'plan'}")
    if missing:
        raise ValueError("Client report is incomplete. Missing plan narrative(s): " + ", ".join(missing))
    if len(expected) > 1 and not (report.get("key_differences") or []):
        raise ValueError("Comparative report contains no key differences")
    return report
