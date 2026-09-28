"""Specialist-agent layer for Ashlar Adviser OS.

Model-backed capabilities are exposed through named specialists and coordinated by
:class:`AshlarOrchestrator`. Deterministic engines (quotes, evidence, policy
lookup) remain outside the model layer and are invoked explicitly by the
orchestrator or a specialist adapter.
"""

from .contracts import (
    OrchestrationDecision,
    OrchestrationIntent,
    OrchestratorResult,
    SpecialistName,
    SpecialistResponse,
)
from .orchestrator import AshlarOrchestrator, get_ashlar_orchestrator

__all__ = [
    "AshlarOrchestrator",
    "OrchestrationDecision",
    "OrchestrationIntent",
    "OrchestratorResult",
    "SpecialistName",
    "SpecialistResponse",
    "get_ashlar_orchestrator",
]
