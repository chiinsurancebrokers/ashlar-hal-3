from __future__ import annotations

from functools import lru_cache
import re
from typing import Any

import httpx

from backend.app.core.config import get_settings


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _provider_tokens(value: str) -> set[str]:
    ignored = {"international", "global", "insurance", "health", "medical", "limited", "ltd"}
    return {part for part in _norm(value).split() if len(part) > 2 and part not in ignored}


class ProposalLibraryClient:
    """Server-only bridge to Proposal Studio's persistent Provider Library."""

    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = str(settings.proposal_library_api_url or "").strip().rstrip("/")
        self.api_key = str(settings.proposal_library_api_key or "").strip()
        self.timeout = float(settings.proposal_library_timeout_seconds or 12)

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def _headers(self) -> dict[str, str]:
        return {"x-ashlar-api-key": self.api_key}

    @lru_cache(maxsize=1)
    def catalog(self) -> tuple[dict[str, Any], ...]:
        if not self.configured:
            return ()
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(f"{self.base_url}/api/v1/library/catalog", headers=self._headers())
        response.raise_for_status()
        rows = response.json().get("catalog") or []
        return tuple(row for row in rows if isinstance(row, dict))

    def match_catalog(self, provider_label: str, product_hint: str | None = None) -> dict[str, Any] | None:
        wanted = _provider_tokens(provider_label)
        wanted_product = _provider_tokens(product_hint or "")
        matches = []
        for row in self.catalog():
            provider = str(row.get("provider") or "")
            tokens = _provider_tokens(provider)
            if not (wanted and tokens and (wanted & tokens)):
                continue
            product_tokens = _provider_tokens(str(row.get("product") or ""))
            if wanted_product and not (wanted_product & product_tokens):
                continue
            matches.append(row)
        if not matches:
            return None
        return sorted(
            matches,
            key=lambda row: (
                str(row.get("version") or ""),
                int(row.get("document_count") or 0),
            ),
            reverse=True,
        )[0]

    def plan_context(self, *, provider_label: str, target_plan: str, product_hint: str | None = None) -> dict[str, Any] | None:
        row = self.match_catalog(provider_label, product_hint)
        if row is None:
            return None
        payload = {
            "provider": row.get("provider"),
            "product": row.get("product"),
            "version": row.get("version"),
            "target_plan": target_plan,
        }
        with httpx.Client(timeout=max(self.timeout, 20.0)) as client:
            response = client.post(
                f"{self.base_url}/api/v1/library/plan-context",
                headers=self._headers(),
                json=payload,
            )
        response.raise_for_status()
        data = response.json()
        data["catalog_match"] = row
        return data


@lru_cache(maxsize=1)
def get_proposal_library_client() -> ProposalLibraryClient:
    return ProposalLibraryClient()
