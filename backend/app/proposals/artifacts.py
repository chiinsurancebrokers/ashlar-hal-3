from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import secrets
import threading

from backend.app.cases.models import AshlarCase


@dataclass(slots=True)
class StoredProposal:
    case_id: str
    client_name: str
    report: dict
    pdf_bytes: bytes
    pptx_bytes: bytes
    created_at: datetime
    expires_at: datetime


class ProposalArtifactStore:
    """Short-lived server-owned storage for rendered proposal artifacts."""

    def __init__(self, *, ttl_minutes: int = 30, max_items: int = 32):
        self.ttl = timedelta(minutes=ttl_minutes)
        self.max_items = max_items
        self._items: dict[str, StoredProposal] = {}
        self._lock = threading.Lock()

    def _prune_locked(self, now: datetime) -> None:
        expired = [key for key, item in self._items.items() if item.expires_at <= now]
        for key in expired:
            self._items.pop(key, None)
        if len(self._items) >= self.max_items:
            oldest = sorted(self._items.items(), key=lambda pair: pair[1].created_at)
            for key, _ in oldest[: max(1, len(self._items) - self.max_items + 1)]:
                self._items.pop(key, None)

    def put(
        self,
        *,
        case: AshlarCase,
        report: dict,
        pdf_bytes: bytes,
        pptx_bytes: bytes,
    ) -> tuple[str, datetime]:
        now = datetime.now(timezone.utc)
        token = secrets.token_urlsafe(24)
        expires = now + self.ttl
        item = StoredProposal(
            case_id=str(case.case_id),
            client_name=case.client.display_name or "Client",
            report=report,
            pdf_bytes=pdf_bytes,
            pptx_bytes=pptx_bytes,
            created_at=now,
            expires_at=expires,
        )
        with self._lock:
            self._prune_locked(now)
            self._items[token] = item
        return token, expires

    def get(self, token: str) -> StoredProposal | None:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._prune_locked(now)
            return self._items.get(token)


def relative_downloads(proposal_id: str, *, api_prefix: str = "/api/v1") -> dict[str, str]:
    base = api_prefix.rstrip("/")
    return {
        "pdf": f"{base}/proposals/{proposal_id}/pdf",
        "pptx": f"{base}/proposals/{proposal_id}/pptx",
    }


PROPOSAL_ARTIFACT_STORE = ProposalArtifactStore()


__all__ = [
    "StoredProposal",
    "ProposalArtifactStore",
    "PROPOSAL_ARTIFACT_STORE",
    "relative_downloads",
]
