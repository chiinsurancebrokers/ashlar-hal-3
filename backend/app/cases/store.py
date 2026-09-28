from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hmac
import secrets
import threading
from typing import Any
from uuid import UUID

from backend.app.cases.models import AshlarCase


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class CaseAnalysisRecord:
    case: AshlarCase
    results: list[dict[str, Any]]
    access_token: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime


class ServerCaseAnalysisStore:
    """Process-local server-owned case/analysis registry.

    The browser never writes verified insurer facts back into this store. It only
    receives an opaque token after HAL has rebuilt the comparison server-side.
    This is deliberately an interface that can later be backed by Supabase or
    another durable store without changing the proposal API contract.
    """

    def __init__(self, *, ttl_hours: int = 12, max_items: int = 256):
        self.ttl = timedelta(hours=ttl_hours)
        self.max_items = max_items
        self._records: dict[UUID, CaseAnalysisRecord] = {}
        self._lock = threading.Lock()

    def _prune_locked(self, now: datetime) -> None:
        expired = [case_id for case_id, record in self._records.items() if record.expires_at <= now]
        for case_id in expired:
            self._records.pop(case_id, None)
        if not getattr(self, "durable", False) and len(self._records) >= self.max_items:
            oldest = sorted(self._records.items(), key=lambda pair: pair[1].updated_at)
            for case_id, _ in oldest[: max(1, len(self._records) - self.max_items + 1)]:
                self._records.pop(case_id, None)

    def put(self, *, case: AshlarCase, results: list[dict[str, Any]]) -> CaseAnalysisRecord:
        now = _utcnow()
        stored_case = case.model_copy(deep=True)
        stored_case.metadata["storage_revision"] = 1
        record = CaseAnalysisRecord(
            case=stored_case,
            results=deepcopy(results),
            access_token=secrets.token_urlsafe(32),
            created_at=now,
            updated_at=now,
            expires_at=now + self.ttl,
        )
        with self._lock:
            self._prune_locked(now)
            self._records[stored_case.case_id] = record
        return self._copy(record)

    def get(self, case_id: UUID, access_token: str) -> CaseAnalysisRecord | None:
        now = _utcnow()
        with self._lock:
            self._prune_locked(now)
            record = self._records.get(case_id)
            if record is None or not access_token or not hmac.compare_digest(record.access_token, access_token):
                return None
            return self._copy(record)

    def save_case(self, *, case: AshlarCase, access_token: str) -> CaseAnalysisRecord | None:
        now = _utcnow()
        with self._lock:
            self._prune_locked(now)
            record = self._records.get(case.case_id)
            if record is None or not access_token or not hmac.compare_digest(record.access_token, access_token):
                return None
            if getattr(self, "durable", False) and case.metadata.get("storage_revision") != record.case.metadata.get("storage_revision"):
                return None
            record.case = case.model_copy(deep=True)
            record.case.metadata["storage_revision"] = int(record.case.metadata.get("storage_revision", 0)) + 1
            record.updated_at = now
            record.expires_at = now + self.ttl
            self._records[case.case_id] = record
            return self._copy(record)

    def save_analysis(
        self,
        *,
        case: AshlarCase,
        results: list[dict[str, Any]],
        access_token: str,
    ) -> CaseAnalysisRecord | None:
        """Atomically persist the Case Brain and its proposal-ready analysis.

        Document analysis changes both the FactLedger and the normalized plan
        analysis consumed by Proposal Studio. Saving them together prevents a
        proposal from seeing a newer case with an older analysis snapshot.
        """

        now = _utcnow()
        with self._lock:
            self._prune_locked(now)
            record = self._records.get(case.case_id)
            if record is None or not access_token or not hmac.compare_digest(record.access_token, access_token):
                return None
            if getattr(self, "durable", False) and case.metadata.get("storage_revision") != record.case.metadata.get("storage_revision"):
                return None
            record.case = case.model_copy(deep=True)
            record.case.metadata["storage_revision"] = int(record.case.metadata.get("storage_revision", 0)) + 1
            record.results = deepcopy(results)
            record.updated_at = now
            record.expires_at = now + self.ttl
            self._records[case.case_id] = record
            return self._copy(record)

    @staticmethod
    def _copy(record: CaseAnalysisRecord) -> CaseAnalysisRecord:
        return CaseAnalysisRecord(
            case=record.case.model_copy(deep=True),
            results=deepcopy(record.results),
            access_token=record.access_token,
            created_at=record.created_at,
            updated_at=record.updated_at,
            expires_at=record.expires_at,
        )


from backend.app.core.durable_store import configure_store

CASE_ANALYSIS_STORE = configure_store(ServerCaseAnalysisStore(), attribute="_records", namespace="cases", record_type=CaseAnalysisRecord, key_type=UUID)
