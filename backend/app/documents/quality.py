"""Evidence quality gate adapted from Ashlar Proposal Studio."""
from __future__ import annotations

from typing import Any


_MISSING = {"", "—", "-", "not specified", "not mentioned", "unclear", "null", "none"}
MATERIAL_BENEFITS = (
    "inpatient",
    "outpatient",
    "cancer",
    "chronic_conditions",
    "mental_health",
    "evacuation_repatriation",
)


def missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().casefold() in _MISSING
    return False


def assess_result_quality(result: dict) -> dict:
    analysis = result.get("analysis") or result
    focused_rows = result.get("focused_rows") or []
    target_plan = (result.get("target_plan") or analysis.get("plan_name") or "").strip()

    missing_fields: list[str] = []
    warnings: list[str] = []

    if analysis.get("error"):
        return {
            "status": "blocked",
            "score": 0,
            "can_generate": False,
            "missing_fields": ["analysis"],
            "warnings": [analysis.get("error")],
        }

    premium = analysis.get("premium") or {}
    if missing(premium.get("amount")):
        missing_fields.append("premium")
    if missing(analysis.get("annual_limit")):
        missing_fields.append("annual limit")
    if missing(analysis.get("deductible_or_excess")):
        missing_fields.append("deductible / excess")
    if missing(analysis.get("area_of_cover")):
        missing_fields.append("area of cover")
    if not target_plan:
        missing_fields.append("selected plan")

    benefits = analysis.get("benefits") or {}
    stated_benefits = sum(not missing(benefits.get(name)) for name in MATERIAL_BENEFITS)
    if stated_benefits < 3:
        warnings.append("Fewer than three material benefit categories were extracted.")

    adapter_meta = analysis.get("carrier_adapter") or {}
    strategy = adapter_meta.get("benefit_strategy") or "generic"
    if result.get("library_source") and not focused_rows and strategy == "multi_plan_table":
        warnings.append("No deterministic target-plan table rows were isolated from the provider library source.")
    elif focused_rows and len(focused_rows) < 5:
        warnings.append("Only a small number of target-plan table rows were isolated; review the brochure structure.")

    warnings.extend(str(x) for x in (analysis.get("extraction_warnings") or []) if x)
    if str(analysis.get("confidence") or "").casefold() == "low":
        warnings.append("AI extraction confidence is low.")

    if adapter_meta.get("adapter_level") == "framework":
        warnings.append(
            f"{adapter_meta.get('carrier_name') or 'Carrier'} adapter is enabled but not yet validated against a real carrier sample in this build."
        )

    if result.get("pricing_status") == "quotation_required" and "premium" in missing_fields:
        return {"status": "blocked", "score": 0, "can_generate": False,
                "missing_fields": missing_fields, "warnings": ["A carrier quotation is required before issuing a proposal."] + warnings}

    critical_missing = {"premium", "annual limit", "selected plan"}.intersection(missing_fields)
    if len(critical_missing) >= 2 or "selected plan" in critical_missing:
        status, can_generate = "blocked", False
    elif missing_fields or warnings:
        status, can_generate = "review", True
    else:
        status, can_generate = "ready", True

    score = max(0, min(100, 100 - 15 * len(missing_fields) - 7 * len(warnings)))
    return {
        "status": status,
        "score": score,
        "can_generate": can_generate,
        "missing_fields": missing_fields,
        "warnings": warnings,
    }


def case_quality(results: list[dict]) -> dict:
    """Aggregate per-plan quality before Proposal Studio renders a client pack."""
    assessments = [assess_result_quality(result) for result in results]
    blocked = [item for item in assessments if not item.get("can_generate")]
    reviews = [item for item in assessments if item.get("status") == "review"]
    return {
        "assessments": assessments,
        "blocked_count": len(blocked),
        "review_count": len(reviews),
        "can_generate": not blocked,
        "status": "blocked" if blocked else ("review" if reviews else "ready"),
    }
