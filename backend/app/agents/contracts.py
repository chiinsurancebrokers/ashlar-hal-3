from __future__ import annotations

from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SpecialistName(str, Enum):
    HAL_ADVISER = "hal_adviser"
    DOCUMENT_ANALYST = "document_analyst"
    PROPOSAL_WRITER = "proposal_writer"
    HEALTH_NAVIGATOR = "health_navigator"


class OrchestrationIntent(str, Enum):
    QUOTE = "quote"
    DOCUMENT = "document"
    ADVICE = "advice"
    PROPOSAL = "proposal"
    HEALTH = "health"
    HEALTH_POLICY = "health_policy"


class StrictAgentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OrchestrationDecision(StrictAgentModel):
    intent: OrchestrationIntent
    specialists: list[SpecialistName] = Field(default_factory=list)
    deterministic_engines: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=500)


class SpecialistResponse(StrictAgentModel):
    specialist: SpecialistName
    status: Literal["completed", "needs_input", "handoff", "unavailable", "blocked"]
    reply: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class OrchestratorResult(StrictAgentModel):
    case_id: UUID | None = None
    decision: OrchestrationDecision
    responses: list[SpecialistResponse] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
