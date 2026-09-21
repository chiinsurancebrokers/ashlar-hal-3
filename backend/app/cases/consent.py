from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from backend.app.cases.models import ConsentRecord, ConsentStatus


class ConsentGate:
    """Explicit bridge from protected health context to insurance context.

    Default is deny. No Asklepios/health field is transferable unless an active
    consent record names that field (or the explicit wildcard ``*``).
    """

    def __init__(self, records: list[ConsentRecord] | None = None):
        self._records = [r.model_copy(deep=True) for r in (records or [])]

    @property
    def records(self) -> list[ConsentRecord]:
        return [r.model_copy(deep=True) for r in self._records]

    def grant(self, *, purpose: str, allowed_fields: list[str], note: str | None = None) -> ConsentRecord:
        record = ConsentRecord(purpose=purpose, allowed_fields=allowed_fields, note=note)
        self._records.append(record)
        return record.model_copy(deep=True)

    def revoke(self, consent_id: UUID) -> ConsentRecord:
        for record in self._records:
            if record.consent_id == consent_id:
                record.status = ConsentStatus.REVOKED
                record.revoked_at = datetime.now(timezone.utc)
                return record.model_copy(deep=True)
        raise KeyError("consent_id not found")

    def allows(self, field_name: str, *, purpose: str | None = None) -> bool:
        field_name = field_name.strip()
        if not field_name:
            return False
        for record in reversed(self._records):
            if record.status != ConsentStatus.GRANTED:
                continue
            if purpose is not None and record.purpose != purpose:
                continue
            if "*" in record.allowed_fields or field_name in record.allowed_fields:
                return True
        return False
