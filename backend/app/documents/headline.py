"""Fast deterministic quote analysis before any LLM document reasoning."""
from __future__ import annotations

from backend.app.documents.carriers import carrier_metadata, get_carrier_adapter
from backend.app.documents.plan_selector import identify_selected_plan


def analyze_quote_headlines(
    quotation_text: str,
    *,
    provider_label: str = "",
    manual_plan_override: str = "",
) -> dict:
    selection = identify_selected_plan(quotation_text, provider_label, manual_plan_override)
    adapter = get_carrier_adapter(provider_label, quotation_text)
    facts = adapter.extract_quote_facts(quotation_text)

    quoted_plan = str(facts.get("quoted_plan") or "").strip()
    selected_plan = str(selection.get("plan_name") or quoted_plan or "").strip()
    confidence = str(selection.get("confidence") or "low")
    if not selection.get("plan_name") and quoted_plan:
        confidence = "high"

    benefits = dict(facts.get("benefit_hints") or {})
    underwriting_basis = facts.get("underwriting_basis") or "Not specified"

    analysis = {
        "provider": provider_label or adapter.display_name,
        "plan_name": selected_plan or None,
        "target_plan_found": bool(selected_plan),
        "premium": facts.get("premium") or {"amount": None, "currency": None, "frequency": None},
        "deductible_or_excess": facts.get("deductible_or_excess") or "Not specified",
        "annual_limit": facts.get("annual_limit") or "Not specified",
        "area_of_cover": facts.get("area_of_cover") or "Not specified",
        "underwriting": {
            "basis": underwriting_basis,
            "pre_existing_conditions": "Not specified",
        },
        "benefits": benefits,
        "waiting_periods": [],
        "optional_benefits": [],
        "critical_limitations": [],
        "source_evidence": [],
        "confidence": confidence,
        "carrier_adapter": carrier_metadata(provider_label, quotation_text),
        "extraction_warnings": list(facts.get("fact_warnings") or []),
        "selected_modules": sorted(facts.get("selected_modules") or []),
        "selection_evidence": selection.get("evidence"),
        "selection_method": selection.get("method"),
    }
    return {
        "provider": analysis["provider"],
        "target_plan": selected_plan,
        "analysis": analysis,
    }
