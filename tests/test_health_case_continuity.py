import asyncio

from backend.app.agents.health_navigator import HealthNavigator
from backend.app.agents.orchestrator import AshlarOrchestrator
from backend.app.cases.models import AshlarCase, CaseStatus
from backend.app.cases.store import CASE_ANALYSIS_STORE


class _FakeAsklepios:
    async def handle(self, *, case_id, message, context):
        return {
            "reply": "Sensitive clinical narrative that must stay in the health domain.",
            "benefit_key": "ct_scan",
            "clinical_detail": "private health detail",
        }


def test_completed_asklepios_navigation_advances_same_case_without_copying_health_narrative():
    record = CASE_ANALYSIS_STORE.put(
        case=AshlarCase(status=CaseStatus.ACTIVE_POLICY),
        results=[],
    )
    orchestrator = AshlarOrchestrator(
        health_navigator=HealthNavigator(backend=_FakeAsklepios())
    )

    result = asyncio.run(orchestrator.handle(
        case_id=record.case.case_id,
        message="I have severe stomach pain.",
        context={"case_token": record.access_token},
    ))

    assert result.responses[0].specialist.value == "health_navigator"
    assert result.responses[0].status == "completed"

    saved = CASE_ANALYSIS_STORE.get(record.case.case_id, record.access_token)
    assert saved is not None
    navigation = saved.case.metadata["health_navigation"]
    assert navigation["status"] == "completed"
    assert navigation["provider"] == "asklepios"
    assert "clinical_detail" not in navigation
    assert "Sensitive clinical narrative" not in str(navigation)
