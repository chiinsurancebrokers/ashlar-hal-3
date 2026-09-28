from __future__ import annotations

from typing import Any

from backend.app.cases.models import AshlarCase, CaseStatus


ADVISER_OS_JOURNEY: tuple[dict[str, Any], ...] = (
    {"order": 1, "key": "insurance_need", "label": "Insurance need", "phase": "discover", "owner": "hal_adviser", "implementation": "live"},
    {"order": 2, "key": "applicant_interview", "label": "Applicant interview", "phase": "discover", "owner": "hal_adviser", "implementation": "live"},
    {"order": 3, "key": "case_created", "label": "AshlarCase created", "phase": "discover", "owner": "ashlar_orchestrator", "implementation": "live"},
    {"order": 4, "key": "quote_engine", "label": "Eligible plans", "phase": "discover", "owner": "quote_engine", "implementation": "live"},
    {"order": 5, "key": "shortlist_selection", "label": "Select 2–4 plans", "phase": "compare", "owner": "hal_adviser", "implementation": "live"},
    {"order": 6, "key": "carrier_documents", "label": "Carrier quotations", "phase": "compare", "owner": "document_analyst", "implementation": "live"},
    {"order": 7, "key": "document_analysis", "label": "Document analysis", "phase": "compare", "owner": "document_analyst", "implementation": "live"},
    {"order": 8, "key": "conflict_check", "label": "Evidence conflict check", "phase": "compare", "owner": "fact_ledger", "implementation": "live"},
    {"order": 9, "key": "verified_comparison", "label": "Verified comparison", "phase": "compare", "owner": "ashlar_orchestrator", "implementation": "live"},
    {"order": 10, "key": "hal_explanation", "label": "HAL explanation", "phase": "compare", "owner": "hal_adviser", "implementation": "live"},
    {"order": 11, "key": "ashlar_assessment", "label": "Ashlar Assessment", "phase": "decide", "owner": "proposal_writer", "implementation": "live"},
    {"order": 12, "key": "proposal_pack", "label": "PDF / PowerPoint proposal", "phase": "decide", "owner": "proposal_writer", "implementation": "live"},
    {"order": 13, "key": "plan_selection", "label": "Client selects plan", "phase": "decide", "owner": "ashlar_orchestrator", "implementation": "next"},
    {"order": 14, "key": "application", "label": "Application preparation", "phase": "decide", "owner": "hal_adviser", "implementation": "foundation"},
    {"order": 15, "key": "policy_issued", "label": "Policy issued", "phase": "policy", "owner": "chi_portal", "implementation": "external_handoff"},
    {"order": 16, "key": "policy_wallet", "label": "Policy record", "phase": "policy", "owner": "chi_portal", "implementation": "external_handoff"},
    {"order": 17, "key": "health_navigation", "label": "Asklepios health navigation", "phase": "care", "owner": "health_navigator", "implementation": "adapter_ready"},
    {"order": 18, "key": "pre_authorisation", "label": "Pre-authorisation", "phase": "care", "owner": "chi_portal", "implementation": "external_handoff"},
    {"order": 19, "key": "claims", "label": "Claims", "phase": "care", "owner": "chi_portal", "implementation": "external_handoff"},
    {"order": 20, "key": "renewal", "label": "Renewal", "phase": "renew", "owner": "chi_portal", "implementation": "external_handoff"},
)

PHASES: tuple[dict[str, str], ...] = (
    {"key": "discover", "label": "Discover"},
    {"key": "compare", "label": "Compare"},
    {"key": "decide", "label": "Decide"},
    {"key": "policy", "label": "Policy"},
    {"key": "care", "label": "Care"},
    {"key": "renew", "label": "Renew"},
)


def _current_phase(case: AshlarCase) -> str:
    if case.status in {CaseStatus.DISCOVERY, CaseStatus.MARKET_REVIEW}:
        return "discover"
    if case.status == CaseStatus.COMPARISON:
        return "compare"
    if case.status in {CaseStatus.PROPOSAL, CaseStatus.APPLICATION}:
        return "decide"
    if case.status == CaseStatus.ACTIVE_POLICY:
        return "policy"
    if case.status == CaseStatus.CLAIM:
        return "care"
    if case.status == CaseStatus.RENEWAL:
        return "renew"
    return "renew" if case.status == CaseStatus.CLOSED else "discover"


def _current_step(case: AshlarCase, intelligence: dict[str, Any]) -> int:
    """Return the highest journey step supported by explicit server-owned state."""

    if case.renewal:
        return 20
    if case.claims or case.status == CaseStatus.CLAIM:
        return 19
    if case.preauthorisations:
        return 18
    if case.metadata.get("health_navigation"):
        return 17
    if case.metadata.get("policy_wallet"):
        return 16
    if case.policy or case.status == CaseStatus.ACTIVE_POLICY:
        return 15
    if case.application or case.status == CaseStatus.APPLICATION:
        return 14
    if case.selected_plan_key:
        return 13
    if case.proposal or case.status == CaseStatus.PROPOSAL:
        return 12
    if case.recommendation:
        return 11

    if intelligence.get("ready_for_proposal"):
        return 9
    if case.facts:
        return 8
    if case.documents:
        return 6
    if case.selected_plan_keys:
        return 5
    if case.applicant:
        return 4
    return 3


def build_journey_snapshot(
    case: AshlarCase,
    *,
    intelligence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    intelligence = intelligence or {}
    current_step = _current_step(case, intelligence)
    current_phase = _current_phase(case)

    stages = []
    for stage in ADVISER_OS_JOURNEY:
        item = dict(stage)
        order = int(item["order"])
        item["state"] = (
            "completed" if order < current_step
            else "current" if order == current_step
            else "upcoming"
        )
        stages.append(item)

    phases = []
    for phase in PHASES:
        orders = [int(stage["order"]) for stage in ADVISER_OS_JOURNEY if stage["phase"] == phase["key"]]
        if not orders:
            continue
        if current_step > max(orders):
            state = "completed"
        elif current_step >= min(orders):
            state = "current"
        else:
            state = "upcoming"
        phases.append({**phase, "state": state})

    return {
        "current_step": current_step,
        "current_phase": current_phase,
        "phases": phases,
        "stages": stages,
    }


__all__ = ["ADVISER_OS_JOURNEY", "PHASES", "build_journey_snapshot"]
