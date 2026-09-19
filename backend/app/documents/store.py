from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
import threading
from uuid import UUID

from backend.app.cases.models import CaseDocument


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _token_digest(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


@dataclass(slots=True)
class StoredDocumentEvidence:
    document_ref: str
    case_id: UUID
    case_token_digest: str
    document: CaseDocument
    provider_label: str
    target_plan: str
    plan_key: str | None
    role: str
    extracted_text: str
    focused_table_context: str
    created_at: datetime
    expires_at: datetime


class ServerDocumentEvidenceStore:
    """Short-lived server-owned carrier-document evidence.

    Raw/extracted carrier material is never accepted back from the browser as
    trusted evidence. The browser receives only an opaque reference bound to the
    same case access token that authorised the upload.
    """

    def __init__(self, *, ttl_hours: int = 2, max_items: int = 128):
        self.ttl = timedelta(hours=ttl_hours)
        self.max_items = max_items
        self._records: dict[str, StoredDocumentEvidence] = {}
        self._lock = threading.Lock()

    def _prune_locked(self, now: datetime) -> None:
        expired = [key for key, item in self._records.items() if item.expires_at <= now]
        for key in expired:
            self._records.pop(key, None)
        if len(self._records) >= self.max_items:
            oldest = sorted(self._records.items(), key=lambda pair: pair[1].created_at)
            for key, _ in oldest[: max(1, len(self._records) - self.max_items + 1)]:
                self._records.pop(key, None)

    def put(
        self,
        *,
        case_id: UUID,
        case_token: str,
        document: CaseDocument,
        provider_label: str,
        target_plan: str,
        role: str,
        extracted_text: str,
        focused_table_context: str = "",
        plan_key: str | None = None,
    ) -> StoredDocumentEvidence:
        now = _utcnow()
        record = StoredDocumentEvidence(
            document_ref=secrets.token_urlsafe(24),
            case_id=case_id,
            case_token_digest=_token_digest(case_token),
            document=document.model_copy(deep=True),
            provider_label=provider_label,
            target_plan=target_plan,
            plan_key=plan_key,
            role=role,
            extracted_text=extracted_text,
            focused_table_context=focused_table_context,
            created_at=now,
            expires_at=now + self.ttl,
        )
        with self._lock:
            self._prune_locked(now)
            self._records[record.document_ref] = record
        return self._copy(record)

    def get(self, document_ref: str, *, case_id: UUID, case_token: str) -> StoredDocumentEvidence | None:
        now = _utcnow()
        expected = _token_digest(case_token)
        with self._lock:
            self._prune_locked(now)
            record = self._records.get(str(document_ref or ""))
            if record is None or record.case_id != case_id:
                return None
            if not hmac.compare_digest(record.case_token_digest, expected):
                return None
            return self._copy(record)

    @staticmethod
    def _copy(record: StoredDocumentEvidence) -> StoredDocumentEvidence:
        return StoredDocumentEvidence(
            document_ref=record.document_ref,
            case_id=record.case_id,
            case_token_digest=record.case_token_digest,
            document=record.document.model_copy(deep=True),
            provider_label=record.provider_label,
            target_plan=record.target_plan,
            plan_key=record.plan_key,
            role=record.role,
            extracted_text=record.extracted_text,
            focused_table_context=record.focused_table_context,
            created_at=record.created_at,
            expires_at=record.expires_at,
        )


DOCUMENT_EVIDENCE_STORE = ServerDocumentEvidenceStore()


__all__ = ["StoredDocumentEvidence", "ServerDocumentEvidenceStore", "DOCUMENT_EVIDENCE_STORE"]
