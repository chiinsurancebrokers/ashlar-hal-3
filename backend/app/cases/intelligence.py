from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.app.cases.fact_ledger import FactLedger
from backend.app.cases.journey import build_journey_snapshot
from backend.app.cases.models import AshlarCase, FactStatus


MATERIAL_KEYS = (
    "premium_amount",
    "annual_limit",
    "deductible_or_excess",
    "area_of_cover",
    "underwriting_basis",
)

_ACTIVE = {
    FactStatus.DECLARED,
    FactStatus.EXTRACTED,
    FactStatus.VERIFIED,
    FactStatus.DISPUTED,
}


def build_case_intelligence(case: AshlarCase) -> dict[str, Any]:
    """Return a deterministic evidence/readiness snapshot for the orchestrator.

    This is intentionally not an LLM task. It tells HAL what is known, what is
    missing, where evidence conflicts, and which action would improve the case
    most before a narrative specialist is asked to explain anything.
    """

    ledger = FactLedger(case.facts)
    conflicts = ledger.conflicts()

    plan_facts: dict[str, list] = defaultdict(list)
    for fact in case.facts:
        if fact.status not in _ACTIVE or not fact.plan_key:
            continue
        plan_facts[fact.plan_key].append(fact)

    current_policy_facts = plan_facts.pop("existing_policy", [])
    plan_keys = list(dict.fromkeys([*case.selected_plan_keys, *plan_facts.keys()]))
    plans: list[dict[str, Any]] = []
    total_material = 0
    available_material = 0

    for plan_key in plan_keys:
        subject = f"plan:{plan_key}"
        active = plan_facts.get(plan_key, [])
        available_keys = sorted({fact.key for fact in active})
        missing_keys: list[str] = []
        conflicting_keys: list[str] = []

        for key in MATERIAL_KEYS:
            total_material += 1
            relevant = [fact for fact in active if fact.key == key]
            if not relevant:
                missing_keys.append(key)
                continue
            if ledger.current(key, subject=subject) is None and len(relevant) > 1:
                conflicting_keys.append(key)
                continue
            available_material += 1

        library_documents = list((case.metadata.get("library_evidence") or {}).get(plan_key) or [])
        library_roles = {
            str(document.get("document_type") or "document").casefold()
            for document in library_documents if isinstance(document, dict)
        }
        roles = sorted({
            str(doc.metadata.get("role") or doc.document_type or "other")
            for doc in case.documents
            if doc.plan_key == plan_key
        } | library_roles)
        provider = next((fact.provider for fact in active if fact.provider), None)

        plans.append({
            "plan_key": plan_key,
            "provider": provider,
            "fact_count": len(active),
            "available_keys": available_keys,
            "missing_material_keys": missing_keys,
            "conflicting_material_keys": conflicting_keys,
            "document_roles": roles,
            "library_documents": library_documents,
            "has_quotation": "quotation" in roles or "quote" in roles or "carrier_quote" in roles,
            "has_brochure_or_tob": any(role in roles for role in ("brochure", "tob", "carrier_tob")),
            "has_wording": any(role in roles for role in ("wording", "policy_wording", "member_guide")),
        })

    conflict_items = [
        {
            "subject": item.subject,
            "key": item.key,
            "fact_ids": [str(value) for value in item.fact_ids],
            "value_count": len(item.values),
        }
        for item in conflicts
    ]

    completeness = (available_material / total_material) if total_material else 0.0
    if not case.facts:
        confidence = "none"
    elif conflicts:
        confidence = "low"
    elif plans and not all(plan["has_quotation"] for plan in plans):
        confidence = "quote-only"
    elif completeness >= 0.8:
        confidence = "high"
    elif completeness >= 0.4:
        confidence = "medium"
    else:
        confidence = "low"

    next_actions: list[dict[str, str]] = []
    if not case.selected_plan_keys:
        next_actions.append({
            "action": "select_shortlist_plans",
            "reason": "Choose 2–4 eligible plans before requesting carrier evidence.",
        })
    elif not case.documents:
        next_actions.append({
            "action": "upload_carrier_documents",
            "reason": "No carrier documents are attached to the selected plans.",
        })
    if conflicts:
        next_actions.append({
            "action": "resolve_evidence_conflicts",
            "reason": f"{len(conflicts)} conflicting fact group(s) must remain explicit before advice is treated as settled.",
        })
    for plan in plans:
        missing_roles: list[str] = []
        if not plan["has_quotation"]:
            missing_roles.append("quotation")
        if not plan["has_brochure_or_tob"]:
            missing_roles.append("brochure_or_tob")
        if not plan["has_wording"]:
            missing_roles.append("policy_wording")
        if missing_roles:
            next_actions.append({
                "action": "complete_plan_evidence",
                "reason": f"{plan['plan_key']} is missing: {', '.join(missing_roles)}.",
            })
        if plan["missing_material_keys"]:
            next_actions.append({
                "action": "verify_material_plan_facts",
                "reason": f"{plan['plan_key']} still lacks: {', '.join(plan['missing_material_keys'])}.",
            })

    ready_for_proposal = bool(plans) and not conflicts and all(
        plan["has_quotation"] and len(plan["missing_material_keys"]) <= 1
        for plan in plans
    )

    snapshot = {
        "case_id": str(case.case_id),
        "case_status": case.status.value,
        "document_count": len(case.documents),
        "fact_count": len(case.facts),
        "selected_plan_count": len(case.selected_plan_keys),
        "plan_count_with_evidence": len(plans),
        "evidence_confidence": confidence,
        "material_completeness": round(completeness, 3),
        "conflict_count": len(conflicts),
        "conflicts": conflict_items,
        "plans": plans,
        "ready_for_proposal": ready_for_proposal,
        "next_actions": next_actions[:10],
        "current_policy": {
            "present": bool(current_policy_facts),
            "fact_count": len(current_policy_facts),
            "provider": next((fact.provider for fact in current_policy_facts if fact.provider), None),
            "available_keys": sorted({fact.key for fact in current_policy_facts}),
        },
    }
    snapshot["journey"] = build_journey_snapshot(case, intelligence=snapshot)
    return snapshot


__all__ = ["MATERIAL_KEYS", "build_case_intelligence"]
