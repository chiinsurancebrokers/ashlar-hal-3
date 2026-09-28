"""Client-facing Proposal Studio analysis embedded in HAL.

This module keeps Proposal Studio's key design: the factual comparison is
constructed deterministically first and the LLM is allowed to write only the
client-facing synthesis around those verified facts.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from backend.app.analysis.client_comparison import build_grounded_case_payload
from backend.app.cases.models import AshlarCase
from .json_utils import parse_best_json_object
from .report_schema import ClientReportValidationError, validate_client_report


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
        x for x in (
            str(premium.get("currency") or "").strip(),
            str(amount).strip(),
            str(premium.get("frequency") or "").strip(),
        ) if x
    )


def client_facing_deductible(value: Any) -> str:
    text = _safe(value)
    if text == "Not specified":
        return text
    parts = [p.strip() for p in re.split(r";|\|", text) if p.strip()]
    kept = []
    for part in parts:
        key = part.casefold()
        if re.search(r"\b0(?:\.0+)?%\s*(?:cost\s*share|co[- ]?insurance)", key):
            continue
        if re.search(r"(?:€|eur|\$|usd|£|gbp)\s*0(?:\.0+)?\s*out[- ]of[- ]pocket", key):
            continue
        kept.append(part)
    return "; ".join(kept) if kept else text


def find_plan_narrative(plans: list[dict], result: dict) -> dict:
    analysis = result.get("analysis") or {}

    def norm(value: Any) -> str:
        return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()

    provider = norm(analysis.get("provider") or result.get("provider"))
    plan = norm(analysis.get("plan_name") or result.get("target_plan"))
    for item in plans or []:
        ip, inn = norm(item.get("provider")), norm(item.get("plan_name"))
        provider_ok = bool(ip and provider and (ip == provider or ip in provider or provider in ip))
        plan_ok = bool(inn and plan and (inn == plan or inn in plan or plan in inn))
        if provider_ok and plan_ok:
            return item
    return {}


def _plan_narrative(plan: dict) -> dict:
    provider = str(plan.get("provider") or "Provider")
    plan_name = str(plan.get("plan_name") or "Plan")
    facts = []
    if plan.get("annual_limit"):
        facts.append(f"annual limit {_safe(plan.get('annual_limit'))}")
    if plan.get("area_of_cover"):
        facts.append(f"cover area {_safe(plan.get('area_of_cover'))}")
    outpatient = (plan.get("benefits") or {}).get("outpatient")
    if outpatient:
        facts.append(f"out-patient {_safe(outpatient)}")
    summary = f"{provider} {plan_name}. " + ("; ".join(facts) + "." if facts else "Verified plan facts are shown in the comparison matrix.")
    considerations = [
        str(x.get("detail") or x.get("topic"))
        for x in (plan.get("critical_limitations") or [])[:4]
        if isinstance(x, dict) and (x.get("detail") or x.get("topic"))
    ]
    return {
        "provider": provider,
        "plan_name": plan_name,
        "positioning": "",
        "summary": summary,
        "strengths": [],
        "considerations": considerations,
        "best_suited_when": "",
        "source_notes": [],
    }


def _fallback_report(payload: dict, language: str) -> dict:
    greek = str(language).lower().startswith(("el", "gr")) or "greek" in str(language).lower()
    return {
        "report_title": "Συγκριτική Ανάλυση Ασφάλισης Υγείας" if greek else "Health Insurance Comparative Analysis",
        "executive_summary": (
            "Η σύγκριση βασίζεται αποκλειστικά στα επαληθευμένα στοιχεία των διαθέσιμων εγγράφων."
            if greek else
            "This comparison is built only from the verified facts available in the supplied plan documents."
        ),
        "client_needs_summary": (
            json.dumps(payload.get("needs_profile") or {}, ensure_ascii=False)
            if payload.get("needs_profile")
            else ("Δεν έχουν δηλωθεί" if greek else "Not supplied")
        ),
        "plans": [_plan_narrative(plan) for plan in payload.get("plans") or []],
        "key_differences": [],
        "ashlar_assessment": {
            "recommended_provider": "",
            "recommended_plan": "",
            "headline": "Απαιτείται αξιολόγηση της σύγκρισης." if greek else "Review the verified comparison before selecting a plan.",
            "reasoning": [
                "Τα στοιχεία παρουσιάζονται χωρίς τεχνητή κατάταξη."
                if greek else
                "The verified facts are presented without manufacturing an AI ranking."
            ],
            "alternative_provider": "",
            "alternative_plan": "",
            "alternative_reason": "",
            "when_the_alternative_may_be_better": "",
            "extras_provider": "",
            "extras_plan": "",
            "extras_reason": "",
            "budget_provider": "",
            "budget_plan": "",
            "budget_reason": "",
        },
        "important_considerations": [],
        "next_steps": [
            "Επιβεβαιώστε την προτιμώμενη επιλογή με τον ασφαλιστικό σας διαμεσολαβητή."
            if greek else
            "Confirm the preferred route with your insurance adviser."
        ],
        "disclaimer": (
            "Η τελική κάλυψη, αποδοχή, εξαιρέσεις και ασφάλιστρο διέπονται από τα επίσημα έγγραφα και την τελική αξιολόγηση της ασφαλιστικής."
            if greek else
            "Final cover, acceptance, exclusions and premium remain subject to the insurer's official documents and final underwriting decision."
        ),
        "comparison_matrix": payload.get("comparison_matrix") or [],
        "client_name": payload.get("client_name") or "Client",
        "case_reference": payload.get("case_reference") or "",
        "client_profile": "",
        "client_priorities": "",
    }


SUMMARY_PROMPT = """You are the advisory-writing layer of Ashlar Proposal Studio embedded inside HAL.
Use ONLY the verified structured case payload below. Never add insurance facts from memory.
Write concise client-facing synthesis. Do not invent numeric scores. Compare the final quoted configurations.
Do not infer health from age or demographics. If two plans are a genuine trade-off, say so rather than manufacturing a winner.
Return JSON only with: executive_summary, client_needs_summary, key_differences, important_considerations.
Each key difference must contain title, analysis and client_impact.
"""

ASSESSMENT_PROMPT = """You are the senior broker-adviser of Ashlar Proposal Studio embedded inside HAL.
Use ONLY the verified case facts and comparison summary provided. Give a primary recommendation only when the evidence and stated needs clearly support one. If two plans are genuinely close on different client-relevant dimensions, leave recommended_provider and recommended_plan empty and explain the trade-off.
Return JSON only with an ashlar_assessment object containing recommended_provider, recommended_plan, headline, reasoning, alternative_provider, alternative_plan, alternative_reason, when_the_alternative_may_be_better, extras_provider, extras_plan, extras_reason, budget_provider, budget_plan, budget_reason.
"""


def _anthropic_json(prompt: str, *, model: str, max_tokens: int) -> dict:
    import anthropic

    client = anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        timeout=float(os.getenv("CLIENT_ANALYSIS_TIMEOUT_SECONDS", "120")),
    )
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
    return parse_best_json_object(text)


def generate_client_analysis(
    *,
    case: AshlarCase,
    results: list[dict],
    language: str = "English",
    strict: bool = False,
) -> dict:
    """Generate a Proposal Studio client report from one shared AshlarCase."""
    payload = build_grounded_case_payload(case, results)
    fallback = _fallback_report(payload, language)
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        if strict:
            raise ClientReportValidationError(
                "ANTHROPIC_API_KEY is not configured for Proposal Studio narrative synthesis."
            )
        return fallback

    model = os.getenv("CLIENT_ANALYSIS_MODEL", os.getenv("CLAUDE_MODEL", "claude-sonnet-5"))
    language_instruction = (
        "Write every client-facing field in Greek."
        if str(language).lower().startswith(("el", "gr")) or "greek" in str(language).lower()
        else "Write every client-facing field in professional English."
    )
    try:
        summary = _anthropic_json(
            SUMMARY_PROMPT
            + "\n"
            + language_instruction
            + "\nVERIFIED CASE:\n"
            + json.dumps(payload, ensure_ascii=False, default=str),
            model=model,
            max_tokens=2600,
        )
        context = {"verified_case": payload, "comparison_summary": summary}
        assessment = _anthropic_json(
            ASSESSMENT_PROMPT
            + "\n"
            + language_instruction
            + "\nCONTEXT:\n"
            + json.dumps(context, ensure_ascii=False, default=str),
            model=model,
            max_tokens=1800,
        ).get("ashlar_assessment") or {}
    except Exception as exc:
        if strict:
            raise ClientReportValidationError(f"Proposal Studio narrative synthesis failed: {exc}") from exc
        fallback["generation_warning"] = str(exc)
        return fallback

    report = dict(fallback)
    report["executive_summary"] = str(
        summary.get("executive_summary") or fallback["executive_summary"]
    ).strip()
    report["client_needs_summary"] = str(
        summary.get("client_needs_summary") or fallback["client_needs_summary"]
    ).strip()
    report["key_differences"] = [
        x for x in (summary.get("key_differences") or []) if isinstance(x, dict)
    ][:5]
    report["important_considerations"] = [
        str(x).strip()
        for x in (summary.get("important_considerations") or [])
        if str(x).strip()
    ][:5]
    if assessment:
        report["ashlar_assessment"] = {**fallback["ashlar_assessment"], **assessment}

    try:
        validate_client_report(report, results)
    except ClientReportValidationError:
        if strict:
            raise
        fallback["generation_warning"] = (
            "Narrative output failed report validation; deterministic Proposal Studio fallback used."
        )
        return fallback
    return report
