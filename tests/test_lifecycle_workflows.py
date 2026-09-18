from datetime import date, timedelta

from backend.app.agents.orchestrator import get_ashlar_orchestrator
from backend.app.cases.models import (
    AshlarCase,
    CaseStatus,
    Fact,
    FactSource,
    FactSourceType,
    FactStatus,
)
from backend.app.cases.store import CASE_ANALYSIS_STORE


def _active_proposal_case():
    plan_key = "carrier:plan_a"
    subject = f"plan:{plan_key}"
    source = FactSource(
        source_type=FactSourceType.POLICY_WORDING,
        source_ref="verified-policy-wording",
    )
    case = AshlarCase(
        status=CaseStatus.PROPOSAL,
        selected_plan_keys=[plan_key, "carrier:plan_b"],
        facts=[
            Fact(
                subject=subject,
                key="annual_limit",
                value="EUR 1,000,000",
                plan_key=plan_key,
                provider="Carrier",
                status=FactStatus.VERIFIED,
                source=source,
            ),
            Fact(
                subject=subject,
                key="area_of_cover",
                value="Worldwide excluding USA",
                plan_key=plan_key,
                provider="Carrier",
                status=FactStatus.VERIFIED,
                source=source,
            ),
            Fact(
                subject=subject,
                key="deductible_or_excess",
                value="EUR 500",
                plan_key=plan_key,
                provider="Carrier",
                status=FactStatus.VERIFIED,
                source=source,
            ),
            Fact(
                subject=subject,
                key="benefit.ct_scan",
                value="Covered subject to pre-authorisation",
                plan_key=plan_key,
                provider="Carrier",
                status=FactStatus.VERIFIED,
                source=source,
            ),
        ],
    )
    return CASE_ANALYSIS_STORE.put(case=case, results=[]), plan_key


def test_stages_13_to_20_remain_on_one_ashlar_case_under_orchestrator():
    record, plan_key = _active_proposal_case()
    orchestrator = get_ashlar_orchestrator()
    case_id = record.case.case_id
    token = record.access_token

    selected = orchestrator.select_final_plan(
        case_id=case_id,
        case_token=token,
        plan_key=plan_key,
        selected_by="client",
    )
    assert selected["action"] == "prepare_application"
    assert selected["case_id"] == str(case_id)
    assert selected["case_intelligence"]["journey"]["current_step"] == 13

    prepared = orchestrator.prepare_application_workflow(
        case_id=case_id,
        case_token=token,
    )
    assert prepared["case_intelligence"]["journey"]["current_step"] == 14
    required = prepared["payload"]["application"]["required_sections"]

    for section in required:
        orchestrator.complete_application_section_workflow(
            case_id=case_id,
            case_token=token,
            section=section,
        )

    submitted = orchestrator.submit_application_workflow(
        case_id=case_id,
        case_token=token,
    )
    assert submitted["payload"]["application"]["status"] == "submitted"

    today = date.today()
    issued = orchestrator.record_policy_issue(
        case_id=case_id,
        case_token=token,
        policy_number="POL-12345",
        provider="Carrier",
        start_date=today,
        renewal_date=today + timedelta(days=365),
        broker_authorized=True,
    )
    assert issued["case_intelligence"]["journey"]["current_step"] == 15

    wallet = orchestrator.policy_wallet(
        case_id=case_id,
        case_token=token,
    )
    assert wallet["payload"]["wallet"]["policy_number"] == "POL-12345"
    assert wallet["payload"]["wallet"]["verified_benefits"]["ct_scan"] == "Covered subject to pre-authorisation"

    preauth = orchestrator.open_preauthorisation(
        case_id=case_id,
        case_token=token,
        service_key="ct_scan",
        provider_name="Dr Example",
        facility_name="Example Hospital",
    )
    assert preauth["policy_evidence"]["verdict"] == "covered"
    assert preauth["case_intelligence"]["journey"]["current_step"] == 18

    claim = orchestrator.open_claim(
        case_id=case_id,
        case_token=token,
        service_date=today,
        amount=250.0,
        currency="EUR",
    )
    assert claim["case_intelligence"]["journey"]["current_step"] == 19

    renewal = orchestrator.start_renewal_workflow(
        case_id=case_id,
        case_token=token,
    )
    assert renewal["action"] == "refresh_renewal_quotes"
    assert renewal["case_id"] == str(case_id)
    assert renewal["case_intelligence"]["journey"]["current_step"] == 20

    final = CASE_ANALYSIS_STORE.get(case_id, token)
    assert final is not None
    assert final.case.case_id == case_id
    assert final.case.selected_plan_key == plan_key
    assert final.case.application is not None
    assert final.case.policy is not None
    assert final.case.preauthorisations
    assert final.case.claims
    assert final.case.renewal is not None
