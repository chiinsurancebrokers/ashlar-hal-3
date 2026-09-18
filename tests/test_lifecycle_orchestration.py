import asyncio
from datetime import date, timedelta

from backend.app.agents.contracts import OrchestrationIntent
from backend.app.agents.orchestrator import classify_orchestration_intent, get_ashlar_orchestrator
from backend.app.cases.models import AshlarCase, CaseStatus
from backend.app.cases.store import CASE_ANALYSIS_STORE
from backend.app.workflows.models import ApplicationRecord, ApplicationStatus


def test_lifecycle_messages_route_to_deterministic_intents():
    assert classify_orchestration_intent("I choose this plan.").intent == OrchestrationIntent.PLAN_SELECTION
    assert classify_orchestration_intent("Let's start the application.").intent == OrchestrationIntent.APPLICATION
    assert classify_orchestration_intent("Show me my Policy Wallet.").intent == OrchestrationIntent.POLICY_WALLET
    assert classify_orchestration_intent("I need pre-authorisation for an MRI.").intent == OrchestrationIntent.PREAUTHORISATION
    assert classify_orchestration_intent("I want to submit a claim.").intent == OrchestrationIntent.CLAIM
    assert classify_orchestration_intent("Let's start the renewal.").intent == OrchestrationIntent.RENEWAL


def test_handle_records_plan_selection_and_starts_application_without_new_model_agent():
    record = CASE_ANALYSIS_STORE.put(
        case=AshlarCase(
            status=CaseStatus.PROPOSAL,
            selected_plan_keys=["carrier:a", "carrier:b"],
        ),
        results=[],
    )
    orchestrator = get_ashlar_orchestrator()

    selected = asyncio.run(orchestrator.handle(
        case_id=record.case.case_id,
        message="I choose this plan.",
        context={
            "case_token": record.access_token,
            "plan_key": "carrier:a",
        },
    ))
    assert selected.decision.intent == OrchestrationIntent.PLAN_SELECTION
    assert selected.decision.specialists == []
    assert selected.payload["workflow"]["action"] == "prepare_application"
    assert selected.next_best_action.action == "prepare_application"

    application = asyncio.run(orchestrator.handle(
        case_id=record.case.case_id,
        message="Let's start the application.",
        context={"case_token": record.access_token},
    ))
    assert application.decision.intent == OrchestrationIntent.APPLICATION
    assert application.decision.specialists == []
    assert application.payload["workflow"]["action"] == "complete_application"
    assert application.next_best_action.action == "complete_application"


def test_renewal_intent_uses_same_case_and_quote_engine():
    application = ApplicationRecord(
        plan_key="carrier:a",
        status=ApplicationStatus.SUBMITTED,
        required_sections=["signature"],
        completed_sections=["signature"],
    )
    today = date.today()
    case = AshlarCase(
        status=CaseStatus.ACTIVE_POLICY,
        selected_plan_keys=["carrier:a"],
        selected_plan_key="carrier:a",
        application=application.model_dump(mode="json"),
        policy={
            "policy_id": "11111111-1111-1111-1111-111111111111",
            "policy_number": "POL-1",
            "provider": "Carrier",
            "plan_key": "carrier:a",
            "start_date": today.isoformat(),
            "renewal_date": (today + timedelta(days=365)).isoformat(),
            "status": "active",
            "document_refs": [],
            "created_at": "2026-09-18T00:00:00+00:00",
        },
    )
    record = CASE_ANALYSIS_STORE.put(case=case, results=[])

    result = asyncio.run(get_ashlar_orchestrator().handle(
        case_id=case.case_id,
        message="Let's start the renewal.",
        context={"case_token": record.access_token},
    ))

    assert result.decision.intent == OrchestrationIntent.RENEWAL
    assert result.case_id == case.case_id
    assert result.payload["workflow"]["action"] == "refresh_renewal_quotes"
