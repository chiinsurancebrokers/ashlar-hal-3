from datetime import date, timedelta

from backend.app.agents.orchestrator import get_ashlar_orchestrator
from backend.app.cases.models import (
    AshlarCase,
    CaseDocument,
    CaseStatus,
    Fact,
    FactSource,
    FactSourceType,
    FactStatus,
)
from backend.app.cases.store import CASE_ANALYSIS_STORE
from backend.app.documents.store import DOCUMENT_EVIDENCE_STORE


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

    evidence = DOCUMENT_EVIDENCE_STORE.put(case_id=case_id, case_token=token,
        document=CaseDocument(filename="synthetic-policy.txt", document_type="policy_schedule", plan_key=plan_key),
        provider_label="Carrier", target_plan="Plan A", role="application", plan_key=plan_key,
        extracted_text="Synthetic issued schedule", original_bytes=b"Synthetic issued schedule")
    for section in required:
        orchestrator.complete_application_section_workflow(
            case_id=case_id,
            case_token=token,
            section=section,
            note="Explicit client evidence reviewed",
            document_refs=[evidence.document_ref],
            broker_authorized=True,
        )

    submitted = orchestrator.submit_application_workflow(
        broker_authorized=True, external_reference="TEST-CARRIER-SUBMISSION",
        case_id=case_id,
        case_token=token,
    )
    assert submitted["payload"]["application"]["status"] == "submitted"

    schedule = DOCUMENT_EVIDENCE_STORE.put(case_id=case_id, case_token=token,
        document=evidence.document, provider_label="Carrier", target_plan="Plan A",
        role="issued_policy", plan_key=plan_key, extracted_text="Issued synthetic policy")
    today = date.today()
    issued = orchestrator.record_policy_issue(
        case_id=case_id,
        case_token=token,
        policy_number="POL-12345",
        provider="Carrier",
        start_date=today,
        renewal_date=today + timedelta(days=365),
        broker_authorized=True,
        document_refs=[schedule.document_ref],
    )
    assert issued["case_intelligence"]["journey"]["current_step"] == 15

    current = CASE_ANALYSIS_STORE.get(case_id, token)
    current.case.metadata["issued_terms_fact_ids"] = {current.case.policy["policy_id"]: [str(f.fact_id) for f in current.case.facts]}
    CASE_ANALYSIS_STORE.save_case(case=current.case, access_token=token)
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
    assert final.case.metadata["application_history"]
    assert final.case.policy is not None
    assert final.case.preauthorisations
    assert final.case.claims
    assert final.case.renewal is not None
