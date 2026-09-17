from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from .contracts import SpecialistName, SpecialistResponse


class HealthNavigatorBackend(Protocol):
    async def handle(
        self,
        *,
        case_id: UUID | None,
        message: str,
        context: dict[str, Any],
    ) -> dict[str, Any]: ...


class HealthNavigator:
    """Asklepios adapter boundary.

    Asklepios/Kira remains a separate health specialist service. The insurance
    code never imports its implementation directly; a backend adapter is
    injected here later. This keeps health model calls isolated and preserves
    the explicit consent boundary before health data crosses into a case.
    """

    name = SpecialistName.HEALTH_NAVIGATOR

    def __init__(self, backend: HealthNavigatorBackend | None = None):
        self.backend = backend

    async def handle(
        self,
        *,
        case_id: UUID | None,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> SpecialistResponse:
        ctx = dict(context or {})
        if self.backend is None:
            return SpecialistResponse(
                specialist=self.name,
                status="handoff",
                reply="This request belongs to Asklepios. The health-service adapter is not connected to Adviser OS yet.",
                payload={
                    "target": "asklepios",
                    "case_id": str(case_id) if case_id else None,
                    "consent_required_for_insurance_transfer": True,
                },
            )

        result = await self.backend.handle(case_id=case_id, message=message, context=ctx)
        reply = str(result.get("reply") or "")
        return SpecialistResponse(
            specialist=self.name,
            status="completed",
            reply=reply,
            payload=dict(result),
        )


_HEALTH_NAVIGATOR = HealthNavigator()


def get_health_navigator() -> HealthNavigator:
    return _HEALTH_NAVIGATOR
