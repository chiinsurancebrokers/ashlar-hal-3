from __future__ import annotations

from uuid import uuid4

import pytest

from backend.app.agents.contracts import SpecialistName, SpecialistResponse
from backend.app.agents.orchestrator import AshlarOrchestrator, classify_orchestration_intent


class _OrderedSpecialist:
    def __init__(self, name: SpecialistName, order: list[str], status: str = "completed"):
        self.name = name
        self.order = order
        self.status = status

    async def handle(self, *, case_id, message, context=None):
        self.order.append(self.name.value)
        return SpecialistResponse(
            specialist=self.name,
            status=self.status,
            reply=f"{self.name.value}: {self.status}",
        )


@pytest.mark.asyncio
async def test_compound_document_proposal_request_runs_specialists_in_safe_order():
    order: list[str] = []
    docs = _OrderedSpecialist(SpecialistName.DOCUMENT_ANALYST, order)
    proposals = _OrderedSpecialist(SpecialistName.PROPOSAL_WRITER, order)
    orchestrator = AshlarOrchestrator(document_analyst=docs, proposal_writer=proposals)

    decision = classify_orchestration_intent("Compare these PDFs and prepare the proposal.")
    assert decision.specialists == [SpecialistName.DOCUMENT_ANALYST, SpecialistName.PROPOSAL_WRITER]
    assert decision.deterministic_engines == ["document_evidence_engine"]

    result = await orchestrator.handle(
        case_id=uuid4(),
        message="Compare these PDFs and prepare the proposal.",
        context={"document_refs": ["opaque-ref"]},
    )

    assert order == ["document_analyst", "proposal_writer"]
    assert [item.specialist.value for item in result.responses] == order


@pytest.mark.asyncio
async def test_compound_plan_stops_before_proposal_when_document_step_is_not_complete():
    order: list[str] = []
    docs = _OrderedSpecialist(SpecialistName.DOCUMENT_ANALYST, order, status="needs_input")
    proposals = _OrderedSpecialist(SpecialistName.PROPOSAL_WRITER, order)
    orchestrator = AshlarOrchestrator(document_analyst=docs, proposal_writer=proposals)

    result = await orchestrator.handle(
        case_id=uuid4(),
        message="Compare these PDFs and prepare the proposal.",
        context={},
    )

    assert order == ["document_analyst"]
    assert result.payload["proposal_step"] == "blocked_until_document_analysis_completes"
