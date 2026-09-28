"""Deep, target-plan-locked insurance document analysis.

This module is the safe bridge between Proposal Studio's document intelligence
and HAL's evidence-first architecture. It deliberately does *not* call an LLM.
Instead it prepares the strict model prompt, parses deterministic target-plan
table evidence, and reapplies exact quote/table facts after model output so
carrier evidence always outranks generated prose.
"""
from __future__ import annotations

from copy import deepcopy
import re

from backend.app.documents.carriers import carrier_metadata, get_carrier_adapter, missing
from backend.app.documents.headline import analyze_quote_headlines


DEEP_ANALYSIS_SCHEMA_PROMPT = """You are the document-analysis engine inside Ashlar HAL.
You are analysing insurance propositions for a professional insurance adviser.

A carrier brochure may contain MANY plan tiers side by side. You receive an
explicit TARGET PLAN and, where available, deterministic TARGET PLAN TABLE
EVIDENCE isolated from that exact plan column. Analyse ONLY the TARGET PLAN.

Evidence priority:
1. Applicant-specific quotation/certificate for selected plan, premium,
   deductible/excess, selected modules, geography and endorsements.
2. Deterministic TARGET PLAN TABLE EVIDENCE for plan-specific benefits.
3. Policy wording/member guide for definitions, exclusions and conditions.
4. Generic brochure prose.

NON-NEGOTIABLE RULES:
- Never borrow a value from a neighbouring tier.
- Do not present an optional benefit as included unless the applicant quote
  confirms it was selected.
- Distinguish Included, Optional-not-selected, Not covered, Not mentioned,
  and Unclear.
- Keep page references when present.
- If the target plan cannot be verified, say so; never guess.
- Brochures are summaries; policy wording/certificate governs.
- Keep diagnostic imaging separate from preventive/wellness benefits.
- Return JSON only using the requested schema.

JSON schema:
{
  "provider": null,
  "plan_name": null,
  "target_plan_found": true,
  "premium": {"amount": null, "currency": null, "frequency": null},
  "deductible_or_excess": "Not specified",
  "annual_limit": "Not specified",
  "area_of_cover": "Not specified",
  "underwriting": {"basis": "Not specified", "pre_existing_conditions": "Not specified"},
  "benefits": {
    "inpatient": "Not mentioned",
    "outpatient": "Not mentioned",
    "cancer": "Not mentioned",
    "chronic_conditions": "Not mentioned",
    "mental_health": "Not mentioned",
    "maternity": "Not mentioned",
    "dental": "Not mentioned",
    "optical": "Not mentioned",
    "diagnostics_imaging": "Not mentioned",
    "preventive": "Not mentioned",
    "evacuation_repatriation": "Not mentioned"
  },
  "waiting_periods": [],
  "optional_benefits": [],
  "critical_limitations": [],
  "source_evidence": [],
  "confidence": "high|medium|low"
}
"""


def build_deep_analysis_prompt(
    *,
    provider_label: str,
    target_plan: str,
    quotation_text: str = "",
    brochure_text: str = "",
    wording_text: str = "",
    focused_table_context: str = "",
) -> str:
    brochure_cap = 35_000 if focused_table_context else 90_000
    target_lock = target_plan or "NOT YET IDENTIFIED"
    return f"""{DEEP_ANALYSIS_SCHEMA_PROMPT}

=== TARGET PLAN LOCK ===
Provider label: {provider_label}
TARGET PLAN: {target_lock}

=== DETERMINISTIC TARGET PLAN TABLE EVIDENCE ===
{focused_table_context[:60_000] or "No deterministic multi-plan table extraction was available."}

=== APPLICANT-SPECIFIC QUOTATION / CERTIFICATE ===
{quotation_text[:50_000] or "Not supplied"}

=== BROCHURE / TABLE OF BENEFITS ===
{brochure_text[:brochure_cap] or "Not supplied"}

=== POLICY WORDING / SUPPORTING TERMS ===
{wording_text[:70_000] or "Not supplied"}
"""


def focused_rows(context: str) -> list[tuple[int | None, str, str]]:
    rows: list[tuple[int | None, str, str]] = []
    for line in (context or "").splitlines():
        match = re.match(r"\[Page\s+(\d+)\]\s+(.+?)\s*=>\s*(.*)$", line.strip())
        if match:
            rows.append((int(match.group(1)), match.group(2).strip(), match.group(3).strip()))
    return rows


def _find_row(rows: list[tuple[int | None, str, str]], *needles: str):
    for row in rows:
        label = row[1].casefold()
        if all(needle.casefold() in label for needle in needles):
            return row
    return None


def _pick_currency_value(value: str, currency: str = "EUR") -> str:
    if not value:
        return ""
    patterns = {
        "EUR": r"€\s*[\d,.]+|EUR\s*[\d,.]+",
        "USD": r"\$\s*[\d,.]+|USD\s*[\d,.]+",
        "GBP": r"£\s*[\d,.]+|GBP\s*[\d,.]+",
    }
    match = re.search(patterns.get((currency or "EUR").upper(), patterns["EUR"]), value, re.I)
    if not match:
        return value
    return match.group(0).replace("EUR", "€").replace("USD", "$").replace("GBP", "£")


def _is_covered(value: str) -> bool:
    key = (value or "").casefold()
    if any(token in key for token in ("not covered", "excluded", "not available", "blank cell")):
        return False
    return any(token in key for token in ("covered", "checkmark", "included", "paid in full"))


def _ensure_shape(result: dict, provider_label: str, target_plan: str) -> dict:
    result = deepcopy(result or {})
    result.setdefault("provider", provider_label)
    result.setdefault("plan_name", target_plan or None)
    result.setdefault("target_plan_found", bool(target_plan))
    result.setdefault("premium", {"amount": None, "currency": None, "frequency": None})
    result.setdefault("deductible_or_excess", "Not specified")
    result.setdefault("annual_limit", "Not specified")
    result.setdefault("area_of_cover", "Not specified")
    result.setdefault("underwriting", {})
    result["underwriting"].setdefault("basis", "Not specified")
    result["underwriting"].setdefault("pre_existing_conditions", "Not specified")
    result.setdefault("benefits", {})
    result.setdefault("waiting_periods", [])
    result.setdefault("optional_benefits", [])
    result.setdefault("critical_limitations", [])
    result.setdefault("source_evidence", [])
    result.setdefault("confidence", "medium")
    return result


def _add_evidence(result: dict, *, field: str, value, document: str, page=None, evidence: str = "") -> None:
    rows = result.setdefault("source_evidence", [])
    signature = (field, str(value), document, page)
    for item in rows:
        if not isinstance(item, dict):
            continue
        if (item.get("field"), str(item.get("value")), item.get("document"), item.get("page")) == signature:
            return
    rows.append({"field": field, "value": value, "document": document, "page": page, "evidence": evidence})


def apply_deterministic_evidence(
    model_result: dict | None,
    *,
    provider_label: str,
    target_plan: str,
    quotation_text: str = "",
    focused_table_context: str = "",
) -> dict:
    """Apply exact quote/table facts after model analysis.

    Exact evidence intentionally overrides conflicting model values. This is
    the anti-hallucination and anti-neighbouring-tier leakage gate.
    """
    result = _ensure_shape(model_result or {}, provider_label, target_plan)
    adapter = get_carrier_adapter(provider_label, quotation_text)
    quote = adapter.extract_quote_facts(quotation_text)
    rows = focused_rows(focused_table_context)

    result["carrier_adapter"] = carrier_metadata(provider_label, quotation_text)
    result["provider"] = provider_label or adapter.display_name
    if target_plan:
        result["plan_name"] = target_plan
        result["target_plan_found"] = True

    premium = quote.get("premium")
    if premium:
        result["premium"] = premium
        _add_evidence(result, field="premium", value=premium, document="Applicant quotation", evidence="Applicant-specific premium")
    if quote.get("deductible_or_excess"):
        result["deductible_or_excess"] = quote["deductible_or_excess"]
        _add_evidence(result, field="deductible_or_excess", value=result["deductible_or_excess"], document="Applicant quotation", evidence="Applicant-specific deductible/excess")
    if quote.get("area_of_cover"):
        result["area_of_cover"] = quote["area_of_cover"]
        _add_evidence(result, field="area_of_cover", value=result["area_of_cover"], document="Applicant quotation", evidence="Applicant-specific area")
    if quote.get("annual_limit"):
        result["annual_limit"] = quote["annual_limit"]
        _add_evidence(result, field="annual_limit", value=result["annual_limit"], document="Applicant quotation", evidence="Applicant-specific annual limit")
    if quote.get("underwriting_basis"):
        result["underwriting"]["basis"] = quote["underwriting_basis"]

    if quote.get("fact_warnings"):
        existing = result.setdefault("extraction_warnings", [])
        for warning in quote["fact_warnings"]:
            if warning not in existing:
                existing.append(warning)

    currency = (result.get("premium") or {}).get("currency") or quote.get("quote_currency") or "EUR"
    benefits = result.setdefault("benefits", {})
    selected_modules = set(quote.get("selected_modules") or [])

    annual = _find_row(rows, "annual overall benefit maximum") or _find_row(rows, "annual maximum plan limit")
    if annual and not quote.get("annual_limit"):
        result["annual_limit"] = _pick_currency_value(annual[2], currency)
        _add_evidence(result, field="annual_limit", value=result["annual_limit"], document="Target-plan table evidence", page=annual[0], evidence=annual[1])
    if annual:
        benefits["inpatient"] = f"Selected core cover; annual overall benefit maximum {_pick_currency_value(annual[2], currency)}."

    outpatient = _find_row(rows, "annual international outpatient benefit maximum") or _find_row(rows, "outpatient", "annual")
    if outpatient and ("outpatient" in selected_modules or not selected_modules):
        benefits["outpatient"] = f"Annual outpatient benefit maximum {_pick_currency_value(outpatient[2], currency)}."
        _add_evidence(result, field="outpatient", value=_pick_currency_value(outpatient[2], currency), document="Target-plan table evidence", page=outpatient[0], evidence=outpatient[1])

    cancer = _find_row(rows, "extensive cancer care") or _find_row(rows, "cancer")
    if cancer:
        benefits["cancer"] = (
            "Cancer care is shown as covered for the selected plan, subject to governing terms."
            if _is_covered(cancer[2]) else cancer[2]
        )

    mental = _find_row(rows, "mental", "health") or _find_row(rows, "mental and behavioural")
    if mental:
        benefits["mental_health"] = mental[2]

    evacuation = _find_row(rows, "medical evacuation")
    if evacuation and ("evacuation" in selected_modules or not selected_modules):
        benefits["evacuation_repatriation"] = evacuation[2] if not _is_covered(evacuation[2]) else "Medical evacuation/repatriation is shown as covered for the selected plan."

    dental = _find_row(rows, "annual dental benefit maximum") or _find_row(rows, "dental")
    if dental and ("vision_dental" in selected_modules or not selected_modules):
        benefits["dental"] = dental[2]

    eye = _find_row(rows, "eye test") or _find_row(rows, "optical")
    if eye and ("vision_dental" in selected_modules or not selected_modules):
        benefits["optical"] = eye[2]

    imaging = next((row for row in rows if re.match(r"^advanced medical imaging\b", row[1].strip(), re.I)), None)
    if imaging:
        benefits["diagnostics_imaging"] = f"Advanced Medical Imaging (MRI/CT/PET): {_pick_currency_value(imaging[2], currency)}."

    routine = _find_row(rows, "routine adult physical examination")
    if routine and ("wellbeing" in selected_modules or not selected_modules):
        benefits["preventive"] = routine[2]

    for key, value in (quote.get("benefit_hints") or {}).items():
        if value and missing(benefits.get(key)):
            benefits[key] = value

    return result


def prepare_deep_analysis(
    *,
    provider_label: str,
    target_plan: str,
    quotation_text: str = "",
    brochure_text: str = "",
    wording_text: str = "",
    focused_table_context: str = "",
    model_result: dict | None = None,
) -> dict:
    """Create the normalized Proposal Studio envelope consumed by the bridge."""
    if model_result is None:
        initial = analyze_quote_headlines(quotation_text, provider_label=provider_label).get("analysis", {})
    else:
        initial = model_result
    analysis = apply_deterministic_evidence(
        initial,
        provider_label=provider_label,
        target_plan=target_plan,
        quotation_text=quotation_text,
        focused_table_context=focused_table_context,
    )
    return {
        "provider": analysis.get("provider") or provider_label,
        "target_plan": target_plan or analysis.get("plan_name") or "",
        "focused_rows": [
            {"page": page, "benefit": label, "value": value}
            for page, label, value in focused_rows(focused_table_context)
        ],
        "analysis": analysis,
        "analysis_prompt": build_deep_analysis_prompt(
            provider_label=provider_label,
            target_plan=target_plan,
            quotation_text=quotation_text,
            brochure_text=brochure_text,
            wording_text=wording_text,
            focused_table_context=focused_table_context,
        ),
    }
