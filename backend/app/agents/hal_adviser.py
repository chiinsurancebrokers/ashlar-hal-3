from __future__ import annotations

from typing import Any
from uuid import UUID

from backend.app.cases.store import CASE_ANALYSIS_STORE
from backend.app.services.orchestrator import chat_turn

from .advice_synthesis import synthesize_case_advice
from .contracts import SpecialistName, SpecialistResponse


class HalAdviser:
    """HAL's client-facing insurance adviser specialist.

    During discovery this preserves the established conversational HAL flow.
    Once a valid server-owned AshlarCase exists, the adviser switches to an
    evidence-aware mode grounded in the stored comparison + FactLedger rather
    than treating the request as a generic chat turn.
    """

    name = SpecialistName.HAL_ADVISER

    async def run_chat(
        self,
        *,
        message: str,
        state: dict[str, Any] | None = None,
        history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return await chat_turn(message, dict(state or {}), list(history or []))

    async def handle(
        self,
        *,
        case_id: UUID | None,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> SpecialistResponse:
        ctx = context or {}
        case_token = str(ctx.get("case_token") or "")

        if case_id is not None and case_token:
            record = CASE_ANALYSIS_STORE.get(case_id, case_token)
            if record is not None:
                advice = await synthesize_case_advice(
                    case=record.case,
                    results=record.results,
                    question=message,
                )
                return SpecialistResponse(
                    specialist=self.name,
                    status="completed",
                    reply=str(advice.get("answer") or ""),
                    payload={
                        "case_id": str(case_id),
                        "mode": "evidence_aware_case_advice",
                        "advice": advice,
                    },
                )

        payload = await self.run_chat(
            message=message,
            state=ctx.get("state") or {},
            history=ctx.get("history") or [],
        )
        return SpecialistResponse(
            specialist=self.name,
            status="completed",
            reply=str(payload.get("reply") or ""),
            payload=payload,
        )


_HAL_ADVISER = HalAdviser()


def get_hal_adviser() -> HalAdviser:
    return _HAL_ADVISER
