from __future__ import annotations

import pytest

from backend.app.agents.contracts import SpecialistName, SpecialistResponse
from backend.app.agents.orchestrator import AshlarOrchestrator
from backend.app.cases.models import CaseStatus
from backend.app.cases.store import CASE_ANALYSIS_STORE


class _CompletedDiscoveryAdviser:
    name = SpecialistName.HAL_ADVISER

    async def handle(self, *, case_id, message, context=None):
        return SpecialistResponse(
            specialist=self.name,
            status="completed",
            reply="Here is the shortlist.",
            payload={
                "reply": "Here is the shortlist.",
                "state": {
                    "discovery_complete": True,
                    "applicant_name": "Client",
                    "age": 42,
                    "residence_country": "Greece",
                    "coverage_area": "area1",
                    "language": "en",
                },
                "quotes": [{"plan_key": "carrier:plan"}],
                "excluded_plans": [],
            },
        )


@pytest.mark.asyncio
async def test_orchestrator_creates_market_case_when_interview_completes():
    orchestrator = AshlarOrchestrator(hal_adviser=_CompletedDiscoveryAdviser())

    result = await orchestrator.handle(
        case_id=None,
        message="Show me my options.",
        context={"state": {}, "history": []},
    )

    assert result.case_id is not None
    response = result.responses[-1]
    token = response.payload["state"]["_adviser_os_case_token"]
    assert response.payload["state"]["_adviser_os_case_id"] == str(result.case_id)

    record = CASE_ANALYSIS_STORE.get(result.case_id, token)
    assert record is not None
    assert record.case.status == CaseStatus.MARKET_REVIEW
    assert record.case.applicant is not None
    assert record.case.applicant.chronic_conditions_note is None
