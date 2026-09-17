from __future__ import annotations

from uuid import uuid4

import pytest

from backend.app.agents.contracts import (
    OrchestrationIntent,
    SpecialistName,
    SpecialistResponse,
)
from backend.app.agents.orchestrator import AshlarOrchestrator, classify_orchestration_intent


@pytest.mark.parametrize(
    ("message", "intent", "specialist", "engine"),
    [
        ("How much would these plans cost?", OrchestrationIntent.QUOTE, None, "quote_engine"),
        ("Compare these PDFs.", OrchestrationIntent.DOCUMENT, SpecialistName.DOCUMENT_ANALYST, "document_evidence_engine"),
        ("Why are you recommending this?", OrchestrationIntent.ADVICE, SpecialistName.HAL_ADVISER, None),
        ("Create the proposal.", OrchestrationIntent.PROPOSAL, SpecialistName.PROPOSAL_WRITER, None),
        ("I have severe stomach pain.", OrchestrationIntent.HEALTH, SpecialistName.HEALTH_NAVIGATOR, None),
        ("Is the CT Asklepios suggested covered?", OrchestrationIntent.HEALTH_POLICY, SpecialistName.HEALTH_NAVIGATOR, "policy_engine"),
    ],
)
def test_deterministic_top_level_routing(message, intent, specialist, engine):
    decision = classify_orchestration_intent(message)
    assert decision.intent == intent
    if specialist is None:
        assert decision.specialists == []
    else:
        assert specialist in decision.specialists
    if engine is not None:
        assert engine in decision.deterministic_engines


class _FakeSpecialist:
    def __init__(self, name: SpecialistName):
        self.name = name
        self.calls = []

    async def handle(self, *, case_id, message, context=None):
        self.calls.append((case_id, message, dict(context or {})))
        return SpecialistResponse(
            specialist=self.name,
            status="completed",
            reply=f"handled by {self.name.value}",
        )

    async def run_chat(self, *, message, state=None, history=None):
        self.calls.append((None, message, {"state": state or {}, "history": history or []}))
        return {"reply": "legacy through specialist", "state": state or {}}


@pytest.mark.asyncio
async def test_advice_is_delegated_only_to_hal_adviser():
    hal = _FakeSpecialist(SpecialistName.HAL_ADVISER)
    docs = _FakeSpecialist(SpecialistName.DOCUMENT_ANALYST)
    proposals = _FakeSpecialist(SpecialistName.PROPOSAL_WRITER)
    health = _FakeSpecialist(SpecialistName.HEALTH_NAVIGATOR)
    orchestrator = AshlarOrchestrator(
        hal_adviser=hal,
        document_analyst=docs,
        proposal_writer=proposals,
        health_navigator=health,
    )

    result = await orchestrator.handle(
        case_id=uuid4(),
        message="Why are you recommending this plan?",
        context={},
    )

    assert result.decision.intent == OrchestrationIntent.ADVICE
    assert len(hal.calls) == 1
    assert docs.calls == []
    assert proposals.calls == []
    assert health.calls == []


@pytest.mark.asyncio
async def test_health_policy_routes_health_first_and_marks_policy_engine():
    hal = _FakeSpecialist(SpecialistName.HAL_ADVISER)
    docs = _FakeSpecialist(SpecialistName.DOCUMENT_ANALYST)
    proposals = _FakeSpecialist(SpecialistName.PROPOSAL_WRITER)
    health = _FakeSpecialist(SpecialistName.HEALTH_NAVIGATOR)
    orchestrator = AshlarOrchestrator(
        hal_adviser=hal,
        document_analyst=docs,
        proposal_writer=proposals,
        health_navigator=health,
    )

    result = await orchestrator.handle(
        case_id=uuid4(),
        message="Is the CT Asklepios suggested covered?",
        context={},
    )

    assert result.decision.intent == OrchestrationIntent.HEALTH_POLICY
    assert result.payload["next_engine"] == "policy_engine"
    assert result.payload["requires_verified_policy_evidence"] is True
    assert result.payload["health_to_insurance_consent_required"] is True
    assert len(health.calls) == 1
    assert hal.calls == []


@pytest.mark.asyncio
async def test_quote_route_does_not_call_a_model_specialist_without_discovery_context():
    hal = _FakeSpecialist(SpecialistName.HAL_ADVISER)
    orchestrator = AshlarOrchestrator(hal_adviser=hal)

    result = await orchestrator.handle(
        case_id=None,
        message="How much would these plans cost?",
        context={},
    )

    assert result.decision.intent == OrchestrationIntent.QUOTE
    assert result.decision.deterministic_engines == ["quote_engine"]
    assert hal.calls == []
    assert result.responses[0].status == "needs_input"


@pytest.mark.asyncio
async def test_legacy_chat_compatibility_also_enters_through_hal_specialist():
    hal = _FakeSpecialist(SpecialistName.HAL_ADVISER)
    orchestrator = AshlarOrchestrator(hal_adviser=hal)

    payload = await orchestrator.handle_legacy_chat(
        message="Hello",
        state={"language": "en"},
        history=[],
    )

    assert payload["reply"] == "legacy through specialist"
    assert len(hal.calls) == 1
