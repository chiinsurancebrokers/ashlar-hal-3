from __future__ import annotations

from typing import Protocol
from uuid import UUID

from backend.app.cases.models import AshlarCase


class CaseRepository(Protocol):
    def create(self, case: AshlarCase) -> AshlarCase: ...
    def get(self, case_id: UUID) -> AshlarCase | None: ...
    def save(self, case: AshlarCase) -> AshlarCase: ...
    def list(self) -> list[AshlarCase]: ...


class InMemoryCaseRepository:
    """Phase-1 repository used by tests and local orchestration.

    Supabase persistence can implement the same protocol in Phase 2. Deep
    copies prevent callers from mutating stored state without an explicit save.
    """

    def __init__(self):
        self._cases: dict[UUID, AshlarCase] = {}

    def create(self, case: AshlarCase) -> AshlarCase:
        if case.case_id in self._cases:
            raise ValueError(f"case {case.case_id} already exists")
        stored = case.model_copy(deep=True)
        self._cases[stored.case_id] = stored
        return stored.model_copy(deep=True)

    def get(self, case_id: UUID) -> AshlarCase | None:
        case = self._cases.get(case_id)
        return case.model_copy(deep=True) if case else None

    def save(self, case: AshlarCase) -> AshlarCase:
        if case.case_id not in self._cases:
            raise KeyError(f"case {case.case_id} does not exist")
        saved = case.model_copy(deep=True)
        saved.touch()
        self._cases[saved.case_id] = saved
        return saved.model_copy(deep=True)

    def list(self) -> list[AshlarCase]:
        return [case.model_copy(deep=True) for case in self._cases.values()]
