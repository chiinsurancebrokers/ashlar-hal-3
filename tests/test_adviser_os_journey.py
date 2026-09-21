from __future__ import annotations

from backend.app.cases.intelligence import build_case_intelligence
from backend.app.cases.journey import ADVISER_OS_JOURNEY, PHASES, build_journey_snapshot
from backend.app.cases.models import AshlarCase, CaseStatus


def test_a_to_z_journey_is_explicit_and_keeps_twenty_ordered_steps():
    assert [stage["order"] for stage in ADVISER_OS_JOURNEY] == list(range(1, 21))
    assert ADVISER_OS_JOURNEY[0]["key"] == "insurance_need"
    assert ADVISER_OS_JOURNEY[-1]["key"] == "renewal"
    assert [phase["key"] for phase in PHASES] == [
        "discover", "compare", "decide", "policy", "care", "renew"
    ]


def test_model_backed_work_is_owned_only_by_declared_specialist_boundaries():
    stage_owner = {stage["key"]: stage["owner"] for stage in ADVISER_OS_JOURNEY}

    assert stage_owner["applicant_interview"] == "hal_adviser"
    assert stage_owner["document_analysis"] == "document_analyst"
    assert stage_owner["ashlar_assessment"] == "proposal_writer"
    assert stage_owner["health_navigation"] == "health_navigator"

    # Pricing / evidence / coverage authority stays deterministic.
    assert stage_owner["quote_engine"] == "quote_engine"
    assert stage_owner["conflict_check"] == "fact_ledger"
    assert stage_owner["policy_issued"] == "chi_portal"
    assert stage_owner["policy_wallet"] == "chi_portal"
    assert stage_owner["pre_authorisation"] == "chi_portal"
    assert stage_owner["claims"] == "chi_portal"
    assert stage_owner["renewal"] == "chi_portal"


def test_journey_snapshot_maps_case_status_to_six_phase_client_experience():
    case = AshlarCase(status=CaseStatus.COMPARISON, selected_plan_keys=["a", "b"])
    snapshot = build_journey_snapshot(case, intelligence={"ready_for_proposal": False})

    assert snapshot["current_phase"] == "compare"
    assert snapshot["current_step"] == 5
    states = {item["key"]: item["state"] for item in snapshot["phases"]}
    assert states["discover"] == "completed"
    assert states["compare"] == "current"
    assert states["decide"] == "upcoming"



def test_next_action_respects_a_to_z_order_before_documents():
    market = AshlarCase(status=CaseStatus.MARKET_REVIEW)
    market_intelligence = build_case_intelligence(market)

    assert market_intelligence["next_actions"][0]["action"] == "select_shortlist_plans"

    comparison = AshlarCase(
        status=CaseStatus.COMPARISON,
        selected_plan_keys=["carrier:a", "carrier:b"],
    )
    comparison_intelligence = build_case_intelligence(comparison)

    assert comparison_intelligence["next_actions"][0]["action"] == "upload_carrier_documents"
