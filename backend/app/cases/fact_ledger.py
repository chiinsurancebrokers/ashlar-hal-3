from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable
from uuid import UUID

from backend.app.cases.models import Fact, FactStatus


_ACTIVE_STATUSES = {FactStatus.DECLARED, FactStatus.EXTRACTED, FactStatus.VERIFIED, FactStatus.DISPUTED}
_STATUS_PRIORITY = {
    FactStatus.VERIFIED: 30,
    FactStatus.DECLARED: 20,
    FactStatus.EXTRACTED: 10,
    FactStatus.DISPUTED: 0,
    FactStatus.SUPERSEDED: -1,
}


def _canonical_value(value) -> str:
    """Stable equality representation for JSON-like values.

    It is used only for conflict detection; the original typed value remains on
    the Fact. ``default=str`` handles UUID/date-like values without making the
    ledger depend on a particular source parser.
    """

    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))


@dataclass(frozen=True)
class FactConflict:
    subject: str
    key: str
    fact_ids: tuple[UUID, ...]
    values: tuple[str, ...]


@dataclass(frozen=True)
class LedgerAddResult:
    fact: Fact
    conflict: bool
    conflicting_fact_ids: tuple[UUID, ...] = ()


class FactLedger:
    """Deterministic in-memory view over case facts.

    The ledger never lets an LLM silently decide between contradictory carrier
    facts. A conflict remains explicit until a caller resolves it or provides a
    superseding verified fact.
    """

    def __init__(self, facts: Iterable[Fact] | None = None):
        self._facts: list[Fact] = [f.model_copy(deep=True) for f in (facts or [])]

    @property
    def facts(self) -> list[Fact]:
        return [f.model_copy(deep=True) for f in self._facts]

    def add(self, fact: Fact) -> LedgerAddResult:
        candidate = fact.model_copy(deep=True)
        self._facts.append(candidate)
        peers = self._active_peers(candidate.subject, candidate.key)
        distinct = self._distinct_values(peers)
        conflict = len(distinct) > 1
        conflicting_ids = tuple(f.fact_id for f in peers if _canonical_value(f.value) != _canonical_value(candidate.value))
        return LedgerAddResult(candidate.model_copy(deep=True), conflict, conflicting_ids)

    def for_key(self, key: str, subject: str = "case", include_superseded: bool = False) -> list[Fact]:
        normalized_key = key.strip().lower().replace(" ", "_")
        return [
            f.model_copy(deep=True)
            for f in self._facts
            if f.subject == subject
            and f.key == normalized_key
            and (include_superseded or f.status != FactStatus.SUPERSEDED)
        ]

    def current(self, key: str, subject: str = "case") -> Fact | None:
        """Return a fact only when the active facts agree on one value.

        If active evidence conflicts, returning ``None`` forces the caller to
        surface the contradiction instead of presenting an arbitrary answer.
        """

        peers = self._active_peers(subject, key)
        if not peers or len(self._distinct_values(peers)) > 1:
            return None
        peers.sort(key=lambda f: (_STATUS_PRIORITY[f.status], f.created_at), reverse=True)
        return peers[0].model_copy(deep=True)

    def conflicts(self) -> list[FactConflict]:
        grouped: dict[tuple[str, str], list[Fact]] = defaultdict(list)
        for fact in self._facts:
            if fact.status in _ACTIVE_STATUSES:
                grouped[(fact.subject, fact.key)].append(fact)

        result: list[FactConflict] = []
        for (subject, key), facts in grouped.items():
            values = self._distinct_values(facts)
            if len(values) > 1:
                result.append(
                    FactConflict(
                        subject=subject,
                        key=key,
                        fact_ids=tuple(f.fact_id for f in facts),
                        values=tuple(sorted(values)),
                    )
                )
        return result

    def resolve(self, *, subject: str, key: str, winning_fact_id: UUID) -> Fact:
        peers = self._active_peers(subject, key)
        winner = next((f for f in peers if f.fact_id == winning_fact_id), None)
        if winner is None:
            raise KeyError("winning_fact_id is not an active fact for this subject/key")

        for fact in self._facts:
            if fact.subject == subject and fact.key == winner.key and fact.fact_id != winning_fact_id and fact.status in _ACTIVE_STATUSES:
                fact.status = FactStatus.SUPERSEDED
        return winner.model_copy(deep=True)

    def _active_peers(self, subject: str, key: str) -> list[Fact]:
        normalized_key = key.strip().lower().replace(" ", "_")
        return [
            f for f in self._facts
            if f.subject == subject and f.key == normalized_key and f.status in _ACTIVE_STATUSES
        ]

    @staticmethod
    def _distinct_values(facts: Iterable[Fact]) -> set[str]:
        return {_canonical_value(f.value) for f in facts}
