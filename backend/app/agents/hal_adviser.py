from __future__ import annotations

from typing import Any
from uuid import UUID

from backend.app.services.orchestrator import chat_turn

from .contracts import SpecialistName, SpecialistResponse


class HalAdviser:
    """HAL's client-facing insurance adviser specialist.

    The existing conversational/Claude path remains intact, but model-backed
    adviser calls are now reached through this specialist boundary when used by
    Adviser OS. The deterministic quote engine inside the legacy chat flow
    remains the source of truth for price and eligibility.
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
